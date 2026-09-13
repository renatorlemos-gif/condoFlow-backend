import pandas as pd
import numpy as np
import re
import xlsxwriter
import io
import warnings
warnings.filterwarnings('ignore')

def processar_extrato_itau_bytes(conteudo_bytes: bytes, nome_arquivo: str = "extrato_itau.xlsx") -> tuple:
    """
    Processa extrato do Banco Itaú (XLSX).
    Retorna (df, excel_io, nome_saida) compatível com o extrato_service.
    """
    df_raw = pd.read_excel(io.BytesIO(conteudo_bytes))
    
    # 1. Encontrar cabeçalho dinamicamente
    cols_raw_upper = [str(c).upper() for c in df_raw.columns]
    if any('DATA' in c for c in cols_raw_upper) and any(any(k in c for k in ['LAN', 'HIST', 'DESC', 'VALOR']) for c in cols_raw_upper):
        df = df_raw.copy()
    else:
        header_idx = 0
        for idx, row in df_raw.iterrows():
            row_str = ' '.join([str(val) for val in row.values]).upper()
            if 'DATA' in row_str and ('LAN' in row_str or 'HIST' in row_str or 'DESC' in row_str or 'VALOR' in row_str):
                header_idx = idx
                break

        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = [str(c).strip() for c in df_raw.iloc[header_idx].values]
        df = df.reset_index(drop=True)

    # 2. Mapeamento de colunas
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
        elif 'VALOR' in col_upper and 'Valor' not in col_map.values():
            col_map[col] = 'Valor'

    df = df.rename(columns=col_map)
    df = df.dropna(subset=['Data'])

    def limpar_valor(val):
        if pd.isna(val): return 0.0
        if isinstance(val, (int, float)): return float(val)
        v_str = str(val).strip().replace('.', '').replace(',', '.')
        try:
            return float(re.sub(r'[^\d\.-]', '', v_str))
        except:
            return 0.0

    # Tratamento de coluna única de Valor (negativo = débito, positivo = crédito)
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

    def parse_data(d):
        if pd.isna(d): return None
        s = str(d).strip()
        match = re.search(r'(\d{2}/\d{2}/\d{4})', s)
        if match: return match.group(1)
        match_iso = re.search(r'(\d{4}-\d{2}-\d{2})', s)
        if match_iso:
            parts = match_iso.group(1).split('-')
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return None

    df['Data_Valida'] = df['Data'].apply(parse_data)
    df = df.dropna(subset=['Data_Valida'])

    # Exclusão de linhas de saldo e totais
    if 'Lançamento' in df.columns:
        lancamentos_str = df['Lançamento'].fillna('').astype(str).str.upper()
        termos_excluir = ['TOTAL', 'SALDO ANTERIOR', 'SALDO FINAL', 'SALDO DO DIA', 'SDO GD']
        mascara_exclusao = lancamentos_str.apply(lambda x: not any(t in x for t in termos_excluir))
        df = df[mascara_exclusao]

    def classificar(linha):
        hist = str(linha.get('Lançamento', '')).upper()
        cred = linha.get('Crédito (R$)', 0.0)
        if any(x in hist for x in ['REND PAGO', 'APL AUT', 'RESG AUT', 'INVEST']): return 'Aplicações/Resgates'
        if any(x in hist for x in ['TARIFA', 'TAR ', 'IOF', 'ANUIDADE']): return 'Tarifas'
        if any(x in hist for x in ['PIX RECEB', 'RECEBIMENTO', 'BOLETO COBRANCA', 'CRED']): return 'Receitas'
        if cred > 0: return 'Outras Receitas'
        return 'Outros Gastos'

    df['Categoria'] = df.apply(classificar, axis=1)

    # 3. Geração do XLSX de saída formatado
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        fmt_header = workbook.add_format({'bold': True, 'bg_color': '#EC7000', 'font_color': 'white', 'border': 1}) # Cor Itaú Laranja
        fmt_moeda = workbook.add_format({'num_format': '#,##0.00'})
        fmt_data = workbook.add_format({'align': 'center'})

        ws = workbook.add_worksheet('Extrato Itaú')
        ws.set_column('A:A', 14)
        ws.set_column('B:B', 45)
        ws.set_column('C:D', 18)
        ws.set_column('E:E', 22)

        headers = ['Data', 'Lançamento', 'Crédito (R$)', 'Débito (R$)', 'Categoria']
        for col_idx, h in enumerate(headers):
            ws.write(0, col_idx, h, fmt_header)

        for row_idx, (_, r) in enumerate(df.iterrows(), start=1):
            ws.write(row_idx, 0, r.get('Data_Valida', ''), fmt_data)
            ws.write(row_idx, 1, str(r.get('Lançamento', '') or ''))
            ws.write(row_idx, 2, float(r.get('Crédito (R$)', 0.0) or 0.0), fmt_moeda)
            ws.write(row_idx, 3, float(r.get('Débito (R$)', 0.0) or 0.0), fmt_moeda)
            ws.write(row_idx, 4, str(r.get('Categoria', '') or ''))

    output.seek(0)
    nome_saida = f"extrato_itau_processado_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return df, output, nome_saida
