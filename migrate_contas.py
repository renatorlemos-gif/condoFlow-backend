import os
from supabase import create_client

def migrate():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    print("Fetching conciliado documents without conta_devedora_id...")
    res = (
        supabase.table("despesas")
        .select("id, conciliacoes(transacoes_extrato(contas_bancarias(plano_conta_id)))")
        .eq("status", "conciliado")
        .is_("conta_devedora_id", "null")
        .execute()
    )
    docs = res.data or []
    print(f"Found {len(docs)} documents to migrate.")

    updated_count = 0
    for d in docs:
        doc_id = d["id"]
        concs = d.get("conciliacoes")
        if concs and isinstance(concs, list) and len(concs) > 0:
            tx = concs[0].get("transacoes_extrato")
            if tx:
                cb = tx.get("contas_bancarias")
                if cb:
                    plano_conta_id = cb.get("plano_conta_id")
                    if plano_conta_id:
                        print(f"Updating doc {doc_id} with plano_conta_id {plano_conta_id}")
                        supabase.table("despesas").update({"conta_devedora_id": plano_conta_id}).eq("id", doc_id).execute()
                        updated_count += 1

    print(f"Migration completed. {updated_count} documents updated.")

if __name__ == "__main__":
    migrate()

