import pandas as pd
import numpy as np
import re
import xlsxwriter
import io
import os
import warnings
warnings.filterwarnings('ignore')

def processar_extrato_santander_bytes(conteudo_bytes: bytes, nome_arquivo: str = "extrato.xlsx") -> tuple[io.BytesIO, str]:
    # 1. LEITURA DOS DADOS
    df_raw = None
    try:
        df_raw = pd.read_excel(io.BytesIO(conteudo_bytes))
    except:
        try:
            df_raw = pd.read_csv(io.BytesIO(conteudo_bytes), sep=';', encoding='latin-1', decimal=',', thousands='.')
        except:
            df_raw = pd.read_html(io.BytesIO(conteudo_bytes), decimal=',', thousands='.')[0]
            
    # Extração rigorosa do "SALDO ANTERIOR" antes de alterar o DataFrame
    saldo_anterior = 0.0
    for idx, row in df_raw.iterrows():
        row_str = ' '.join([str(val) for val in row.values]).upper()
        if 'SALDO ANTERIOR' in row_str:
            numeros = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', row_str)
            if numeros:
                val_str = numeros[-1].replace('.', '').replace(',', '.')
                saldo_anterior = float(val_str)
            break

    # Localizar a linha do cabeçalho real de forma inteligente
    col_str = ' '.join([str(c) for c in df_raw.columns]).upper()
    
    if 'DATA' in col_str and any(x in col_str for x in ['HIST', 'LAN', 'DOCTO', 'DESC']):
        df = df_raw.copy()
    else:
        header_idx = -1
        for idx, row in df_raw.iterrows():
            row_str = ' '.join([str(val) for val in row.values]).upper()
            if 'DATA' in row_str and any(x in row_str for x in ['HIST', 'LAN', 'DOCTO', 'DESC']):
                header_idx = idx
                break
                
        if header_idx != -1:
            df = df_raw.iloc[header_idx:].reset_index(drop=True)
            df.columns = df.iloc[0]
            df = df[1:].reset_index(drop=True)
        else:
            df = df_raw.copy()

    # Limpar espaços invisíveis nos nomes das colunas
    df.columns = [str(c).strip() for c in df.columns]
    
    # Padronizar nomes de colunas
    col_map = {}
    for col in df.columns:
        col_str = str(col).upper()
        if 'DATA' in col_str: col_map[col] = 'Data'
        elif any(x in col_str for x in ['HIST', 'LAN', 'DESC']): col_map[col] = 'Lançamento'
        elif 'CR' in col_str: col_map[col] = 'Crédito (R$)'
        elif 'DÉB' in col_str or 'DEB' in col_str: col_map[col] = 'Débito (R$)'
        elif 'VALOR' in col_str: col_map[col] = 'Valor'

    df = df.rename(columns=col_map)
    
    # Tratamento caso o Santander unifique Crédito/Débito na coluna 'Valor'
    if 'Valor' in df.columns and 'Crédito (R$)' not in df.columns:
        def converter_valor(v):
            if pd.isna(v): return 0.0
            v_str = str(v).replace('.', '').replace(',', '.')
            try: return float(re.sub(r'[^\d\.-]', '', v_str))
            except: return 0.0
        
        df['ValorNum'] = df['Valor'].apply(converter_valor)
        df['Crédito (R$)'] = df['ValorNum'].apply(lambda x: x if x > 0 else 0.0)
        df['Débito (R$)'] = df['ValorNum'].apply(lambda x: abs(x) if x < 0 else 0.0)
    else:
        for col in ['Crédito (R$)', 'Débito (R$)']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace('.', '').str.replace(',', '.')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            else:
                df[col] = 0.0

    # 2. LIMPEZA DE DADOS
    def parse_data(d):
        if pd.isna(d): return None
        match = re.search(r'(\d{2}/\d{2}/\d{4})', str(d).strip())
        return match.group(1) if match else None

    if 'Data' not in df.columns:
        raise ValueError("A coluna 'Data' não pôde ser identificada no extrato do Santander.")

    df['Data_Valida'] = df['Data'].apply(parse_data)
    df = df.dropna(subset=['Data_Valida'])
    
    termos_excluir = ['TOTAL', 'SALDO ANTERIOR', 'SALDO']
    if 'Lançamento' in df.columns:
        df = df[~df['Lançamento'].fillna('').astype(str).str.upper().apply(lambda x: any(t in x for t in termos_excluir))]
    
    df['Mes_Ano'] = df['Data_Valida'].apply(lambda x: x[3:])
    if not df.empty and 'Mes_Ano' in df.columns:
        mes_principal = df['Mes_Ano'].mode()[0]
        df = df[df['Mes_Ano'] == mes_principal]

    # 3. CATEGORIZAÇÃO (DIRETRIZES DO SANTANDER)
    def classificar_santander(linha):
        hist = str(linha.get('Lançamento', '')).upper()
        cred = linha.get('Crédito (R$)', 0.0)
        
        # Ajuste realizado aqui: pega qualquer lançamento que comece com 'TAR '
        if 'TARIFA' in hist or hist.startswith('TAR '): return 'Tarifas'
        if 'IOF' in hist: return 'IOF'
        if 'RESGATE CONTAMAX' in hist: return 'Resgates Contamax'
        if 'RESGATE' in hist and 'CONTAMAX' not in hist: return 'Resgates'
        if 'CR COB' in hist: return 'Receitas'
        if 'APLICACAO CONTAMAX' in hist or 'APLICAÇÃO CONTAMAX' in hist: return 'Aplicações Contamax'
        if ('APLICACAO' in hist or 'APLICAÇÃO' in hist) and 'CONTAMAX' not in hist: return 'Aplicações'
        
        if cred > 0: return 'Outras Receitas'
        return 'Outros Gastos'

    df['Categoria'] = df.apply(classificar_santander, axis=1)

    # 4. EXPORTAÇÃO PARA O EXCEL CONSOLIDADO EM MEMÓRIA
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        fmt_header = workbook.add_format({'bold': True, 'bg_color': '#CC0000', 'font_color': 'white', 'border': 1})
        fmt_cat = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
        fmt_total = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1, 'num_format': '#,##0.00'})
        fmt_moeda = workbook.add_format({'num_format': '#,##0.00'})
        fmt_data = workbook.add_format({'align': 'center'})

        ws_det = workbook.add_worksheet('Detalhado')
        ws_det.set_column('A:A', 12)
        ws_det.set_column('B:B', 55)
        ws_det.set_column('C:D', 18)

        categorias_ordem = [
            'Tarifas', 'IOF', 'Resgates Contamax', 'Resgates', 
            'Receitas', 'Aplicações Contamax', 'Aplicações', 
            'Outras Receitas', 'Outros Gastos'
        ]
        
        linha_atual = 0
        mapeamento_totais = {}

        for cat in categorias_ordem:
            df_cat = df[df['Categoria'] == cat]
            if df_cat.empty: continue
                
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
                val_cred = float(row_data.get('Crédito (R$)', 0.0))
                val_deb = float(row_data.get('Débito (R$)', 0.0))
                
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
    
    return output, nome_saida