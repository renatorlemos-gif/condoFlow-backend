import io
import csv
from fastapi import HTTPException
from supabase import Client
import locale

class ExportadorService:
    def __init__(self, db_client: Client):
        self.db = db_client

    def obter_preview_us42(self, condominio_id: str, competencia: str) -> list:
        # competencia is usually in YYYY-MM format from mesAnoSelecionado
        prefix = competencia
        if "/" in competencia:
            mes, ano = competencia.split("/")
            prefix = f"{ano}-{mes}"

        # 1. Despesas validados
        res_val = (
            self.db.table("despesas")
            .select("id, fornecedor, numero_doc, data_pagamento, data_emissao, valor_total, descricao, sugestao_contabil, conta_despesa_id, fonte_pagadora_id, plano_contas(codigo_contabil), fontes_pagadoras(plano_conta_id, plano_contas(codigo_contabil, descricao))")
            .eq("condominio_id", condominio_id)
            .eq("status", "validado")
            .not_.is_("conta_despesa_id", "null")
            .execute()
        )
        
        # 2. Despesas conciliados
        res_conc = (
            self.db.table("despesas")
            .select("id, fornecedor, numero_doc, data_pagamento, data_emissao, valor_total, descricao, sugestao_contabil, conta_despesa_id, fonte_pagadora_id, plano_contas(codigo_contabil), fontes_pagadoras(plano_conta_id, plano_contas(codigo_contabil, descricao))")
            .eq("condominio_id", condominio_id)
            .eq("status", "conciliado")
            .not_.is_("conta_despesa_id", "null")
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

        despesas = []
        for d in docs_val + docs_conc:
            conta_despesa = d.get("plano_contas") or {}
            conta_deb = conta_despesa.get("codigo_contabil") or ""
            
            fp = d.get("fontes_pagadoras") or {}
            fp_pc = fp.get("plano_contas") or {}
            conta_cred = fp_pc.get("codigo_contabil") or ""
                            
            despesas.append({
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
            
        return despesas

    def gerar_lote_us42(self, condominio_id: str, competencia: str) -> bytes:
        despesas = self.obter_preview_us42(condominio_id, competencia)

        if not despesas:
            raise HTTPException(status_code=400, detail="Nuo ho lanamentos qualificados para exportauo neste perodo.")

        import logging
        logger = logging.getLogger("exportador")
        output = io.StringIO()

        for doc in despesas:
            # C. Credora (Banco/Fonte - diminui o ativo)
            conta_cred = doc.get("conta_cred") or ""
            
            # C. Devedora (Despesa - aumenta a despesa)
            conta_deb = doc.get("conta_deb") or ""

            if not conta_cred or not conta_deb:
                logger.warning(f"Despesa {doc.get('id')} ignorado na exportação: Partida Dobrada incompleta.")
                continue

            raw_date = doc.get("data_pagamento") or doc.get("data_emissao") or ""
            data_fmt = ""
            if raw_date:
                raw_date = raw_date[:10]
                yyyy, mm, dd = raw_date.split("-")
                data_fmt = f"{dd}/{mm}/{yyyy}"
            
            val = float(doc.get("valor_total") or 0)
            val_cents = str(int(round(val * 100)))
            
            fornecedor = doc.get("fornecedor") or ""
            descricao = doc.get("descricao") or ""
            
            historico = descricao or f"PG {fornecedor}"
            # Substituir vírgulas e quebras de linha por espaço
            historico = historico.replace(",", " ").replace("\n", " ").replace("\r", " ")
            
            # Layout sem posição fixa com vírgulas como separador
            part_0 = "  "
            part_1 = str(conta_cred)
            part_2 = str(conta_deb)
            part_3 = data_fmt
            
            # DT_COTA (MM/YYYY)
            dt_cota = ""
            if raw_date:
                dt_cota = f"{mm}/{yyyy}"
            part_4 = dt_cota
            
            part_5 = historico
            part_6 = val_cents
            
            linha = f"{part_0},{part_1},{part_2},{part_3},{part_4},{part_5},{part_6},\n"
            output.write(linha)
            
        return output.getvalue().encode("cp1252", errors="replace")


