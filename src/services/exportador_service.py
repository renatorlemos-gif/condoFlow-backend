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
        
        for doc in documentos:
            raw_date = doc.get("data_pagamento") or doc.get("data_emissao") or ""
            data_fmt = ""
            if raw_date:
                raw_date = raw_date[:10]
                yyyy, mm, dd = raw_date.split("-")
                data_fmt = f"{dd}/{mm}/{yyyy}"

            conta_deb = doc.get("conta_codigo") or ""
            
            # C. Devedora (Banco)
            plano = doc.get("plano_contas") or {}
            conta_cred = plano.get("codigo") or ""
            
            val = float(doc.get("valor_total") or 0)
            val_cents = str(int(round(val * 100)))
            
            fornecedor = doc.get("fornecedor") or ""
            descricao = doc.get("descricao") or ""
            numero_doc = str(doc.get("numero_doc") or "S/N")
            
            historico = descricao or f"PG {fornecedor}"
            
            # Formatao com tamanho fixo e vrgulas
            part_0 = "  "
            part_1 = f"{conta_deb:<3}"[:3]
            part_2 = f"{conta_cred:<3}"[:3]
            part_3 = f"{data_fmt:<10}"[:10]
            
            # DT_COTA (MM/YYYY)
            dt_cota = ""
            if raw_date:
                dt_cota = f"{mm}/{yyyy}"
            part_4 = f"{dt_cota:<7}"[:7]
            
            part_5 = f"{historico:<80}"[:80]
            part_6 = f"{val_cents:0>8}"[-8:]
            part_7 = f"{numero_doc:<5}"[:5]
            part_8 = "  "
            
            linha = f"{part_0},{part_1},{part_2},{part_3},{part_4},{part_5},{part_6},{part_7},{part_8}\n"
            output.write(linha)
                
        return output.getvalue().encode("cp1252", errors="replace")

    def obter_preview_us42(self, condominio_id: str, competencia: str) -> list:
        # competencia is usually in YYYY-MM format from mesAnoSelecionado
        prefix = competencia
        if "/" in competencia:
            mes, ano = competencia.split("/")
            prefix = f"{ano}-{mes}"

        # 1. Documentos validados
        res_val = (
            self.db.table("documentos_fiscais")
            .select("id, fornecedor, numero_doc, data_pagamento, data_emissao, valor_total, descricao, sugestao_contabil, conta_devedora_id, plano_contas(codigo)")
            .eq("condominio_id", condominio_id)
            .eq("status", "validado")
            .not_.is_("conta_devedora_id", "null")
            .execute()
        )
        
        # 2. Documentos conciliados
        res_conc = (
            self.db.table("documentos_fiscais")
            .select("id, fornecedor, numero_doc, data_pagamento, data_emissao, valor_total, descricao, sugestao_contabil, conta_devedora_id, plano_contas(codigo)")
            .eq("condominio_id", condominio_id)
            .eq("status", "conciliado")
            .not_.is_("conta_devedora_id", "null")
            .execute()
        )

        docs_val = []
        for d in (res_val.data or []):
            dt = d.get("data_pagamento") or d.get("data_emissao")
            if dt and dt.startswith(prefix):
                docs_val.append(d)

        docs_conc = []
        for d in (res_conc.data or []):
            dt = d.get("data_pagamento") or d.get("data_emissao")
            if dt and dt.startswith(prefix):
                docs_conc.append(d)

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
            
        return documentos

    def gerar_lote_us42(self, condominio_id: str, competencia: str) -> bytes:
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
            
            historico = descricao or f"PG {fornecedor}"
            # Garantia de 80 chars e sem vírgulas (segurança dupla no backend)
            historico = historico.replace(",", " ")[:80]
            
            # Layout fixo com vírgulas como separador (sem NR_DOC)
            # BRANCO(2), CDCONTACREDORA(3), CDCONTADEVEDORA(3), DTLANC(10), DT_COTA(7), DSCOMPHISTORICO(80), VLLANC(8), BRANCO(2)
            part_0 = "  "
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
            
            linha = f"{part_0},{part_1},{part_2},{part_3},{part_4},{part_5},{part_6},\n"
            output.write(linha)
            
        return output.getvalue().encode("cp1252", errors="replace")
