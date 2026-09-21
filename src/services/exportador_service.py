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
