import sys

file_path = '/app/src/services/exportador_service.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

start_str = '    def gerar_lote_us42(self, condominio_id: str, competencia: str) -> bytes:'
end_str = '        return output.getvalue().encode("cp1252", errors="replace")'

start_idx = content.find(start_str)
end_idx = content.find(end_str, start_idx) + len(end_str)

if start_idx == -1 or end_idx == -1:
    print('Indices not found')
    sys.exit(1)

new_block = '''    def gerar_lote_us42(self, condominio_id: str, competencia: str) -> bytes:
        documentos = self.obter_preview_us42(condominio_id, competencia)

        if not documentos:
            raise HTTPException(status_code=400, detail="Nuo ho lanamentos qualificados para exportauo neste perodo.")

        output = io.StringIO()
        
        for doc in documentos:
            raw_date = doc.get("data_pagamento") or doc.get("data_emissao") or ""
            data_fmt = ""
            if raw_date:
                raw_date = raw_date[:10]
                yyyy, mm, dd = raw_date.split("-")
                data_fmt = f"{dd}/{mm}/{yyyy}"

            # C. Credora (Despesa) - em preview us42 vem como conta_deb
            conta_cred = doc.get("conta_deb", "")
            
            # C. Devedora (Banco) - em preview us42 vem como conta_cred
            conta_deb = doc.get("conta_cred", "")
            
            val = float(doc.get("valor_total") or 0)
            val_cents = str(int(round(val * 100)))
            
            fornecedor = doc.get("fornecedor") or ""
            descricao = doc.get("descricao") or ""
            numero_doc = str(doc.get("numero_doc") or "S/N")
            
            historico = descricao or f"PG {fornecedor}"
            
            # Formatao com tamanho fixo e vrgulas
            part_0 = "   "
            part_1 = f"{conta_cred:<3}"[:3]
            part_2 = f"{conta_deb:<3}"[:3]
            part_3 = f"{data_fmt:<10}"[:10]
            
            # DT_COTA (MM/YYYY)
            dt_cota = ""
            if raw_date:
                dt_cota = f"{mm}/{yyyy}"
            part_4 = f"{dt_cota:<7}"[:7]
            
            part_5 = f"{historico:<80}"[:80]
            part_6 = f"{val_cents:0>8}"[-8:]
            part_7 = f"{numero_doc:<5}"[:5]
            part_8 = "   "
            
            linha = f"{part_0},{part_1},{part_2},{part_3},{part_4},{part_5},{part_6},{part_7},{part_8}\\n"
            output.write(linha)
            
        return output.getvalue().encode("cp1252", errors="replace")'''

new_content = content[:start_idx] + new_block + content[end_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Successfully updated exportador_service.py for us42')

