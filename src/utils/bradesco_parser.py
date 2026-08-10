import pandas as pd
import numpy as np
import re
import xlsxwriter
import io
import warnings
warnings.filterwarnings('ignore')

def processar_extrato_bradesco_bytes(conteudo_bytes: bytes) -> io.BytesIO:
    # Leitura direta do arquivo Excel gerado pelo Bradesco Net Empresa
    df_raw = pd.read_excel(io.BytesIO(conteudo_bytes))
    
    # O extrato do Bradesco Net Empresa sempre possui o cabeçalho na linha 7 (índice 7)
    header_idx = 7
    if header_idx >= len(df_raw):
        header_idx = 0
        for idx, row in df_raw.iterrows():
            row_str = ' '.join([str(val) for val in row.values]).upper()
            if 'DATA' in row_str and ('LAN' in row_str or 'HIST' in row_str):
                header_idx = idx
                break

    # Extração segura do Saldo Anterior
    saldo_anterior = 0.0
    for idx in range(header_idx, min(header_idx + 5, len(df_raw))):
        row_str = ' '.join([str(val) for val in df_raw.iloc[idx].values]).upper()
        if 'SALDO ANTERIOR' in row_str:
            numeros = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', row_str)
            if numeros:
                val_str = numeros[-1].replace('.', '').replace(',', '.')
                saldo_anterior = float(val_str)
            break

    # Montagem do DataFrame a partir do cabeçalho
    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = [str(c).strip() for c in df_raw.iloc[header_idx].values]
    df = df.reset_index(drop=True)

    # Padronização garantida das colunas principais baseada nas posições do Bradesco
    cols = list(df.columns)
    col_map = {}
    if len(cols) > 0: col_map[cols[0]] = 'Data'
    if len(cols) > 1: col_map[cols[1]] = 'Lançamento'
    if len(cols) > 3: col_map[cols[3]] = 'Crédito (R$)'
    if len(cols) > 4: col_map[cols[4]] = 'Débito (R$)'

    df = df.rename(columns=col_map)
    df = df.dropna(subset=['Data'])

    # Limpeza de valores numéricos
    def limpar_valor(val):
        if pd.isna(val): return 0.0
        v_str = str(val).strip().replace('.', '').replace(',', '.')
        try:
            return float(re.sub(r'[^\d\.-]', '', v_str))
        except:
            return 0.0

    if 'Crédito (R$)' in df.columns:
        df['Crédito (R$)'] = df['Crédito (R$)'].apply(limpar_valor)
    else:
        df['Crédito (R$)'] = 0.0

    if 'Débito (R$)' in df.columns:
        df['Débito (R$)'] = df['Débito (R$)'].apply(lambda x: abs(limpar_valor(x)))
    else:
        df['Débito (R$)'] = 0.0

    # Validação de datas válidas (formato DD/MM/AAAA)
    def parse_data(d):
        if pd.isna(d): return None
        match = re.search(r'(\d{2}/\d{2}/\d{4})', str(d).strip())
        return match.group(1) if match else None

    df['Data_Valida'] = df['Data'].apply(parse_data)
    df = df.dropna(subset=['Data_Valida'])

    # Excluir linhas indesejadas (Saldo Anterior, Totais, etc.)
    if 'Lançamento' in df.columns:
        lancamentos_str = df['Lançamento'].fillna('').astype(str).str.upper()
        termos_excluir = ['TOTAL', 'SALDO ANTERIOR', 'SALDO']
        mascara_exclusao = lancamentos_str.apply(lambda x: not any(t in x for t in termos_excluir))
        df = df[mascara_exclusao]

    # Filtrar pelo mês principal para isolar o extrato do mês vigente
    if not df.empty and 'Data_Valida' in df.columns:
        df['Mes_Ano'] = df['Data_Valida'].apply(lambda x: str(x)[3:])
        if not df['Mes_Ano'].empty:
            mes_principal = df['Mes_Ano'].mode()[0]
            df = df[df['Mes_Ano'] == mes_principal]

    # 3. CATEGORIZAÇÃO
    def classificar(linha):
        hist = str(linha.get('Lançamento', '')).upper()
        cred = linha.get('Crédito (R$)', 0.0)
        
        if any(x in hist for x in ['RENTAB', 'INVEST']): return 'Rentabilidades'
        if any(x in hist for x in ['RESG/']): return 'Resgates'
        if any(x in hist for x in ['APLICACAO', 'APLIC/', 'APLIC ']): return 'Aplicações'
        if any(x in hist for x in ['TARIFA', 'TAR ', 'IOF']): return 'Tarifas'
        if 'LIQUIDACAO DE COBRANCA' in hist: return 'Receitas'
        
        if cred > 0: return 'Outras Receitas'
        return 'Outros Gastos'

    df['Categoria'] = df.apply(classificar, axis=1)

    # 4. GERAÇÃO DO ARQUIVO EXCEL CONSOLIDADO EM MEMÓRIA
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        fmt_header = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
        fmt_cat = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1})
        fmt_total = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9', 'border': 1, 'num_format': '#,##0.00'})
        fmt_moeda = workbook.add_format({'num_format': '#,##0.00'})
        fmt_data = workbook.add_format({'align': 'center'})

        ws_det = workbook.add_worksheet('Detalhado')
        ws_det.set_column('A:A', 12)
        ws_det.set_column('B:B', 50)
        ws_det.set_column('C:D', 18)

        categorias_ordem = ['Rentabilidades', 'Resgates', 'Aplicações', 'Tarifas', 'Receitas', 'Outras Receitas', 'Outros Gastos']
        linha_atual = 0 
        resumo_totais = []

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
                
                # Aplica sinal negativo nos débitos da aba Detalhado
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
            
            resumo_totais.append({
                'Categoria': cat,
                'Credito': float(df_cat['Crédito (R$)'].sum()),
                'Debito': float(df_cat['Débito (R$)'].sum())
            })
            
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
        for item in resumo_totais:
            ws_cons.write(linha_cons, 0, f"Total {item['Categoria']}", fmt_cat)
            ws_cons.write(linha_cons, 3, item['Credito'], fmt_moeda)
            ws_cons.write(linha_cons, 4, -abs(item['Debito']), fmt_moeda) 
            linha_cons += 1
            
        n = linha_cons 
        
        ws_cons.write(linha_cons, 0, 'Saldo Final', fmt_total)
        formula_final = f'=E2 + (SUM(D3:D{n}) - (SUM(E3:E{n})*-1))'
        ws_cons.write_formula(linha_cons, 4, formula_final, fmt_total)

    output.seek(0)
    return output