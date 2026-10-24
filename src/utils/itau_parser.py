import io
import os
import re
import warnings
import pandas as pd
import numpy as np
import xlsxwriter

warnings.filterwarnings('ignore')


def limpar_valor(val) -> float:
    """
    Normaliza valores monetários para float com suporte flexível a:
    - Formato brasileiro com vírgula decimal (ex: 46.085,89 ou -27,52 ou 1.250,50)
    - Formato com ponto decimal (ex: 46085.89 ou -4216.93 ou 1,250.50)
    - Números já numéricos (int, float)
    """
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    if not s:
        return 0.0

    # Remove símbolos monetários e caracteres estranhos, preservando dígitos, pontos, vírgulas e sinais
    s = re.sub(r'[^\d.,\-+]', '', s)
    if not s:
        return 0.0

    # Se contém ambos ponto e vírgula
    if '.' in s and ',' in s:
        if s.rfind(',') > s.rfind('.'):
            # Formato brasileiro: 1.234,56
            s = s.replace('.', '').replace(',', '.')
        else:
            # Formato internacional: 1,234.56
            s = s.replace(',', '')
    elif ',' in s:
        # Apenas vírgula: 1234,56 ou 27,52
        s = s.replace(',', '.')
    elif '.' in s:
        # Apenas pontos: se mais de um ponto (ex: 1.234.567), remove todos
        if s.count('.') > 1:
            s = s.replace('.', '')
        # Se for um único ponto, assume separador decimal (ex: 46085.89, -4216.93)

    try:
        return float(s)
    except Exception:
        return 0.0


def carregar_dados_brutos(conteudo_bytes: bytes) -> pd.DataFrame:
    """
    Ingestão resiliente de arquivo binário:
    1. Tenta pd.read_excel
    2. Fallback encadeado para pd.read_csv com múltiplos encodings e separadores.
    """
    # 1. Tentativa com Excel
    try:
        df_excel = pd.read_excel(io.BytesIO(conteudo_bytes), header=None)
        if not df_excel.empty and df_excel.shape[1] >= 2:
            return df_excel
    except Exception:
        pass

    # 2. Fallback iterativo para CSV
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    separadores = [',', ';', '\t']

    for enc in encodings:
        for sep in separadores:
            try:
                df_csv = pd.read_csv(
                    io.BytesIO(conteudo_bytes),
                    sep=sep,
                    encoding=enc,
                    header=None,
                    dtype=str,
                    on_bad_lines='skip',
                    skip_blank_lines=True
                )
                if not df_csv.empty and df_csv.shape[1] >= 2:
                    return df_csv
            except Exception:
                continue

    raise ValueError("Não foi possível ler o arquivo de extrato do Itaú como Excel ou CSV.")


def extrair_saldo_anterior(df_raw: pd.DataFrame) -> float:
    """
    Localiza a ocorrência de 'SALDO ANTERIOR' no extrato bruto e extrai o valor numérico.
    """
    saldo = 0.0
    for _, row in df_raw.iterrows():
        row_str = ' '.join([str(val) for val in row.values if pd.notna(val)]).upper()
        if 'SALDO ANTERIOR' in row_str:
            # Varre as células da direita para a esquerda procurando o valor
            for val in reversed(row.values):
                if pd.isna(val):
                    continue
                v_str = str(val).strip()
                # Ignora a própria descrição ou datas
                if 'SALDO' in v_str.upper() or re.search(r'\d{2}/\d{2}/\d{4}', v_str):
                    continue
                v_limpo = limpar_valor(val)
                if v_limpo != 0.0 or v_str in ['0', '0.0', '0,00', '0.00']:
                    saldo = float(v_limpo)
                    return saldo

            # Fallback regex na linha inteira excluindo datas
            str_sem_data = re.sub(r'\d{2}/\d{2}/\d{4}', '', row_str)
            nums = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+\.\d{2}', str_sem_data)
            if nums:
                saldo = float(limpar_valor(nums[-1]))
                return saldo
            break

    return saldo


def classificar_itau(linha) -> str:
    """
    Taxonomia padronizada do Banco Itaú em 7 categorias contábeis canônicas.
    """
    hist = str(linha.get('Lançamento', '')).upper()
    cred = float(linha.get('Crédito (R$)', 0.0) or 0.0)

    # 1. Rentabilidades
    if any(x in hist for x in ['REND PAGO', 'RENDIMENTO', 'REMUNERACAO', 'REMUNERAÇÃO', 'REND APLIC', 'REND ']):
        return 'Rentabilidades'

    # 2. Resgates
    if any(x in hist for x in ['RESGATE', 'RESG AUT', 'RESG/']):
        return 'Resgates'

    # 3. Aplicações
    if any(x in hist for x in ['APLICACAO', 'APLICAÇÃO', 'APLIC/', 'APLIC ', 'APL AUT', 'APL.AUTOM', 'INVEST']):
        return 'Aplicações'

    # 4. Tarifas
    if any(x in hist for x in ['TAR/CUSTAS', 'TARIFA', 'TAR ', 'CUSTAS COBRANCA', 'CUSTAS COBRANÇA', 'IOF', 'ANUIDADE']):
        return 'Tarifas'

    # 5. Receitas (Arrecadação de Cotas Condominiais / Boletos Recebidos)
    if any(x in hist for x in ['BOLETOS RECEBIDOS', 'BOLETO COBRANCA', 'BOLETO COBRANÇA', 'LIQUIDACAO DE COBRANCA', 'LIQUIDAÇÃO DE COBRANÇA', 'LIQ COBRANCA', 'RECEBIMENTO', 'PIX RECEB']):
        return 'Receitas'

    # 6. Outras Receitas (Fallback de Créditos)
    if cred > 0:
        return 'Outras Receitas'

    # 7. Outros Gastos (Todos os pagamentos e despesas operacionais do condomínio)
    # Ex: BOLETO PAGO, PIX ENVIADO, SISPAG, RSHOP, transferências, taxas e concessionárias
    return 'Outros Gastos'


def processar_extrato_itau_bytes(conteudo_bytes: bytes, nome_arquivo: str = "extrato_itau.xlsx") -> tuple:
    """
    Processa extrato do Banco Itaú (XLSX, XLS ou CSV).
    Retorna (df, excel_io, nome_saida) em conformidade com o extrato_service.
    """
    # 1. Carga resiliente em memória
    df_raw = carregar_dados_brutos(conteudo_bytes)

    # 2. Extração do Saldo Anterior antes do expurgo
    saldo_anterior = extrair_saldo_anterior(df_raw)

    # 3. Localização dinâmica da linha de cabeçalho
    header_idx = -1
    for idx, row in df_raw.iterrows():
        row_str = ' '.join([str(val) for val in row.values if pd.notna(val)]).upper()
        if 'DATA' in row_str and any(k in row_str for k in ['LAN', 'HIST', 'DESC', 'VALOR', 'ORIGEM']):
            header_idx = idx
            break

    if header_idx != -1:
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = [str(c).strip() for c in df_raw.iloc[header_idx].values]
        df = df.reset_index(drop=True)
    else:
        df = df_raw.copy()
        df.columns = [str(c).strip() for c in df.columns]

    # 4. Mapeamento de colunas
    cols = list(df.columns)
    col_map = {}
    for col in cols:
        col_upper = str(col).upper()
        if 'DATA' in col_upper and 'Data' not in col_map.values():
            col_map[col] = 'Data'
        elif any(k in col_upper for k in ['LAN', 'HIST', 'DESC']) and 'Lançamento' not in col_map.values():
            col_map[col] = 'Lançamento'
        elif any(k in col_upper for k in ['CRÉD', 'CRED', 'ENTRADA']) and 'Crédito (R$)' not in col_map.values():
            col_map[col] = 'Crédito (R$)'
        elif any(k in col_upper for k in ['DÉB', 'DEB', 'SAÍDA', 'SAIDA']) and 'Débito (R$)' not in col_map.values():
            col_map[col] = 'Débito (R$)'
        elif 'VALOR' in col_upper and 'SALDO' not in col_upper and 'Valor' not in col_map.values():
            col_map[col] = 'Valor'

    df = df.rename(columns=col_map)

    # 5. Normalização de valores numéricos
    if 'Valor' in df.columns and 'Crédito (R$)' not in df.columns and 'Débito (R$)' not in df.columns:
        df['Valor_Num'] = df['Valor'].apply(limpar_valor)
        df['Crédito (R$)'] = df['Valor_Num'].apply(lambda x: x if x > 0 else 0.0)
        df['Débito (R$)'] = df['Valor_Num'].apply(lambda x: abs(x) if x < 0 else 0.0)
    else:
        if 'Crédito (R$)' in df.columns:
            df['Crédito (R$)'] = df['Crédito (R$)'].apply(limpar_valor)
        else:
            df['Crédito (R$)'] = 0.0

        if 'Débito (R$)' in df.columns:
            df['Débito (R$)'] = df['Débito (R$)'].apply(lambda x: abs(limpar_valor(x)))
        else:
            df['Débito (R$)'] = 0.0

    # 6. Validação e parsing de datas
    def parse_data(d):
        if pd.isna(d):
            return None
        s = str(d).strip()
        match = re.search(r'(\d{2}/\d{2}/\d{4})', s)
        if match:
            return match.group(1)
        match_iso = re.search(r'(\d{4}-\d{2}-\d{2})', s)
        if match_iso:
            parts = match_iso.group(1).split('-')
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return None

    if 'Data' in df.columns:
        df['Data_Valida'] = df['Data'].apply(parse_data)
        df = df.dropna(subset=['Data_Valida'])
    else:
        df['Data_Valida'] = None
        df = df.dropna(subset=['Data_Valida'])

    # 7. Expurgo rigoroso de saldos transitórios e diários
    termos_excluir = [
        'TOTAL',
        'SALDO ANTERIOR',
        'SALDO TOTAL DISPONÍVEL DIA',
        'SALDO TOTAL DISPONIVEL DIA',
        'SALDO DO DIA',
        'SALDO FINAL',
        'SDO GD',
        'SDO CTA',
        'SALDO'
    ]
    if 'Lançamento' in df.columns:
        lancamentos_str = df['Lançamento'].fillna('').astype(str).str.upper()
        mascara_exclusao = lancamentos_str.apply(lambda x: not any(t in x for t in termos_excluir))
        df = df[mascara_exclusao]

    # 8. Alinhamento de competência predominante
    if not df.empty and 'Data_Valida' in df.columns:
        df['Mes_Ano'] = df['Data_Valida'].apply(lambda x: str(x)[3:])
        if not df['Mes_Ano'].empty:
            mes_principal = df['Mes_Ano'].mode()[0]
            df = df[df['Mes_Ano'] == mes_principal].copy()

    # 9. Classificação contábil determinística
    df['Categoria'] = df.apply(classificar_itau, axis=1)

    # 10. Geração de Workbook XLSX via xlsxwriter (Duas abas: Detalhado e Consolidado com Paleta Itaú)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        # Paleta institucional Itaú: Laranja #EC7000 e cinza #D9D9D9
        fmt_header = workbook.add_format({'bold': True, 'bg_color': '#EC7000', 'font_color': 'white', 'border': 1})
        fmt_cat = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
        fmt_total = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1, 'num_format': '#,##0.00'})
        fmt_moeda = workbook.add_format({'num_format': '#,##0.00'})
        fmt_data = workbook.add_format({'align': 'center'})

        # Aba Detalhado
        ws_det = workbook.add_worksheet('Detalhado')
        ws_det.set_column('A:A', 12)
        ws_det.set_column('B:B', 50)
        ws_det.set_column('C:D', 18)

        categorias_ordem = ['Rentabilidades', 'Resgates', 'Aplicações', 'Tarifas', 'Receitas', 'Outras Receitas', 'Outros Gastos']
        linha_atual = 0
        mapeamento_totais = {}

        for cat in categorias_ordem:
            df_cat = df[df['Categoria'] == cat]
            if df_cat.empty:
                continue

            ws_det.merge_range(linha_atual, 0, linha_atual, 3, cat, fmt_cat)
            linha_atual += 1
            ws_det.write(linha_atual, 0, 'Data', fmt_header)
            ws_det.write(linha_atual, 1, 'Lançamento', fmt_header)
            ws_det.write(linha_atual, 2, 'Crédito (R$)', fmt_header)
            ws_det.write(linha_atual, 3, 'Débito (R$)', fmt_header)
            linha_atual += 1

            linha_inicio = linha_atual + 1
            for _, row_data in df_cat.iterrows():
                val_data = str(row_data.get('Data_Valida', ''))
                val_lanc = str(row_data.get('Lançamento', ''))
                val_cred = float(row_data.get('Crédito (R$)', 0.0) or 0.0)
                val_deb = float(row_data.get('Débito (R$)', 0.0) or 0.0)
                val_deb_negativo = -abs(val_deb) if val_deb > 0 else 0.0

                ws_det.write(linha_atual, 0, val_data, fmt_data)
                ws_det.write(linha_atual, 1, val_lanc)
                ws_det.write(linha_atual, 2, val_cred, fmt_moeda)
                ws_det.write(linha_atual, 3, val_deb_negativo, fmt_moeda)
                linha_atual += 1

            linha_fim = linha_atual
            ws_det.write(linha_atual, 0, f'Total {cat}', fmt_total)
            ws_det.write(linha_atual, 1, '', fmt_total)
            ws_det.write_formula(linha_atual, 2, f'=SUM(C{linha_inicio}:C{linha_fim})', fmt_total)
            ws_det.write_formula(linha_atual, 3, f'=SUM(D{linha_inicio}:D{linha_fim})', fmt_total)
            mapeamento_totais[cat] = linha_atual + 1
            linha_atual += 2

        # Aba Consolidado
        ws_cons = workbook.add_worksheet('Consolidado')
        ws_cons.set_column('A:A', 35)
        ws_cons.set_column('D:E', 20)

        ws_cons.write('A1', 'Categoria', fmt_header)
        ws_cons.write('D1', 'Crédito (R$)', fmt_header)
        ws_cons.write('E1', 'Débito (R$)', fmt_header)

        ws_cons.write('A2', 'Saldo Anterior', fmt_cat)
        ws_cons.write('E2', float(saldo_anterior), fmt_moeda)

        linha_cons = 2
        for cat in categorias_ordem:
            if cat not in mapeamento_totais:
                continue
            lin_det = mapeamento_totais[cat]
            ws_cons.write(linha_cons, 0, f"Total {cat}", fmt_cat)
            ws_cons.write_formula(linha_cons, 3, f"=Detalhado!C{lin_det}", fmt_moeda)
            ws_cons.write_formula(linha_cons, 4, f"=Detalhado!D{lin_det}", fmt_moeda)
            linha_cons += 1

        n = linha_cons
        ws_cons.write(linha_cons, 0, 'Saldo Final', fmt_total)
        formula_final = f'=E2 + (SUM(D3:D{n}) - (SUM(E3:E{n})*-1))'
        ws_cons.write_formula(linha_cons, 4, formula_final, fmt_total)

    output.seek(0)
    nome_base, _ = os.path.splitext(os.path.basename(nome_arquivo))
    nome_saida = f"{nome_base}_PROC.xlsx"

    return df, output, nome_saida
