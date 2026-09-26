import io
import csv
from fastapi import HTTPException
from supabase import Client
import locale

class ExportadorService:
    def __init__(self, db_client: Client):
        self.db = db_client

    def gerar_lote_alterdata(self, condominio_id: str) -> bytes:
        # Busca transações conciliadas do condomínio
        result = (
            self.db.table("transacoes_extrato")
            .select(
                "id, data_transacao, valor, descricao, banco, "
                "conciliacoes!inner(id, documento_id, documentos_fiscais(fornecedor, numero_doc, descricao, sugestao_contabil, valor_total))"
            )
            .eq("condominio_id", condominio_id)
            .execute()
        )

        transacoes = result.data or []

        if not transacoes:
             raise HTTPException(status_code=400, detail="Nenhum lançamento conciliado encontrado para exportação.")

        pendencias = []
        
        # Validar pendências ("A Classificar" ou null)
        for t in transacoes:
            concs = t.get("conciliacoes") or []
            for c in concs:
                doc = c.get("documentos_fiscais") or {}
                sugestao = doc.get("sugestao_contabil")
                
                if not sugestao:
                    pendencias.append(t["id"])
                    continue
                    
                nome_debito = sugestao.get("conta_debito_nome", "")
                if "A Classificar" in nome_debito or not sugestao.get("conta_debito_codigo"):
                    pendencias.append(t["id"])

        if pendencias:
            raise HTTPException(
                status_code=400, 
                detail="Existem lançamentos com conta 'A Classificar' ou sem classificação. Regularize antes de exportar."
            )

        # Gerar CSV em formato Windows-1252 com virgula para decimal
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', lineterminator='\n')
        
        # Cabeçalho opcional (Alterdata geralmente ignora a 1a linha se for texto, mas para segurança podemos omitir ou deixar)
        writer.writerow([
            "Lançamento Automático", "Conta Débito", "Conta Crédito", "Data", 
            "Valor", "Código Histórico", "Complemento Histórico", 
            "Centro Custo Débito", "Centro Custo Crédito", "Número Documento"
        ])
        
        for t in transacoes:
            data_trans_str = t.get("data_transacao", "")
            if data_trans_str:
                data_trans_str = data_trans_str[:10]
                yyyy, mm, dd = data_trans_str.split("-")
                data_fmt = f"{dd}/{mm}/{yyyy}"
            else:
                data_fmt = ""
                
            concs = t.get("conciliacoes") or []
            
            for c in concs:
                doc = c.get("documentos_fiscais") or {}
                sugestao = doc.get("sugestao_contabil") or {}
                
                conta_deb = sugestao.get("conta_debito_codigo", "")
                conta_cred = sugestao.get("conta_credito_codigo", "")
                
                # Se conciliado em lote, o valor da parcela é o valor do documento, senão o da transação
                val = float(doc.get("valor_total") or t.get("valor") or 0)
                val_fmt = f"{val:.2f}".replace(".", ",")
                
                fornecedor = doc.get("fornecedor", "Fornecedor") or "Fornecedor"
                numero_doc = doc.get("numero_doc", "S/N") or "S/N"
                descricao = doc.get("descricao") or t.get("descricao") or ""
                
                # Histórico: "Vlr. ref. [Doc] [Forn] conf. [Desc]"
                historico = f"Vlr. ref. {numero_doc} {fornecedor} conf. {descricao}"
                
                # Layout Padrão Alterdata 10 colunas:
                # 1: Lançamento Auto, 2: Débito, 3: Crédito, 4: Data, 5: Valor, 
                # 6: Cód Histórico, 7: Complemento Histórico, 8: CC Débito, 9: CC Crédito, 10: Nº Doc
                writer.writerow([
                    "",           # 1. Código Lançamento Automático
                    conta_deb,    # 2. Conta Débito
                    conta_cred,   # 3. Conta Crédito
                    data_fmt,     # 4. Data
                    val_fmt,      # 5. Valor
                    "",           # 6. Código do Histórico
                    historico,    # 7. Complemento Histórico
                    "",           # 8. Centro Custo Débito
                    "",           # 9. Centro Custo Crédito
                    numero_doc    # 10. Número Documento
                ])
                
        # Retornar o CSV em bytes com encoding Windows-1252
        return output.getvalue().encode("cp1252", errors="replace")

    def obter_preview_us42(self, condominio_id: str, competencia: str) -> list:
        # 1. Documentos validados
        res_val = (
            self.db.table("documentos_fiscais")
            .select("id, fornecedor, numero_doc, data_pagamento, data_emissao, valor_total, descricao, sugestao_contabil, conta_devedora_id, plano_contas(codigo)")
            .eq("condominio_id", condominio_id)
            .eq("competencia", competencia)
            .eq("status", "validado")
            .not_.is_("conta_devedora_id", "null")
            .execute()
        )
        docs_val = res_val.data or []

        # 2. Documentos conciliados
        res_conc = (
            self.db.table("documentos_fiscais")
            .select("id, fornecedor, numero_doc, data_pagamento, data_emissao, valor_total, descricao, sugestao_contabil, conciliacoes(transacoes_extrato(contas_bancarias(plano_contas(codigo))))")
            .eq("condominio_id", condominio_id)
            .eq("competencia", competencia)
            .eq("status", "conciliado")
            .execute()
        )
        docs_conc = res_conc.data or []

        documentos = []
        for d in docs_val:
            sugestao = d.get("sugestao_contabil") or {}
            conta_deb = sugestao.get("conta_debito_codigo", "")
            conta_cred = d.get("plano_contas", {}).get("codigo", "") if d.get("plano_contas") else ""
            
            documentos.append({
                "id": d["id"],
                "fornecedor": d.get("fornecedor"),
                "numero_doc": d.get("numero_doc"),
                "data_pagamento": d.get("data_pagamento"),
                "data_emissao": d.get("data_emissao"),
                "valor_total": d.get("valor_total"),
                "descricao": d.get("descricao"),
                "conta_deb": conta_deb,
                "conta_cred": conta_cred
            })

        for d in docs_conc:
            sugestao = d.get("sugestao_contabil") or {}
            conta_deb = sugestao.get("conta_debito_codigo", "")
            
            conta_cred = ""
            concs = d.get("conciliacoes") or []
            if concs and isinstance(concs, list):
                tx = concs[0].get("transacoes_extrato")
                if tx:
                    cb = tx.get("contas_bancarias")
                    if cb:
                        pc = cb.get("plano_contas")
                        if pc:
                            conta_cred = pc.get("codigo", "")
                            
            documentos.append({
                "id": d["id"],
                "fornecedor": d.get("fornecedor"),
                "numero_doc": d.get("numero_doc"),
                "data_pagamento": d.get("data_pagamento"),
                "data_emissao": d.get("data_emissao"),
                "valor_total": d.get("valor_total"),
                "descricao": d.get("descricao"),
                "conta_deb": conta_deb,
                "conta_cred": conta_cred
            })
            
        return documentos

    def gerar_lote_us42(self, condominio_id: str, competencia: str) -> bytes:
        documentos = self.obter_preview_us42(condominio_id, competencia)

        if not documentos:
            raise HTTPException(status_code=400, detail="Não há lançamentos qualificados para exportação neste período.")

        output = io.StringIO()
        writer = csv.writer(output, delimiter=',', lineterminator='\n')
        
        for doc in documentos:
            raw_date = doc.get("data_pagamento") or doc.get("data_emissao") or ""
            data_fmt = ""
            if raw_date:
                raw_date = raw_date[:10]
                yyyy, mm, dd = raw_date.split("-")
                data_fmt = f"{dd}/{mm}/{yyyy}"

            conta_deb = doc.get("conta_deb", "")
            conta_cred = doc.get("conta_cred", "")
            
            val = float(doc.get("valor_total") or 0)
            val_int = int(val)
            val_fmt = str(val_int)
            
            fornecedor = doc.get("fornecedor") or ""
            descricao = doc.get("descricao") or ""
            numero_doc = doc.get("numero_doc") or "S/N"
            
            historico = doc.get("descricao") or f"PG {fornecedor}"
            
            writer.writerow([
                data_fmt,     
                conta_deb,    
                conta_cred,   
                val_fmt,      
                historico     
            ])
                
        return output.getvalue().encode("cp1252", errors="replace")
