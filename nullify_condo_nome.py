import os
from supabase import create_client

def run():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    print("Nullifying condo_nome in despesas...")
    
    # We can fetch all and update or try to do it effectively
    # Actually, we can just update all where condo_nome = 'Condominio' or is not null
    res = supabase.table("despesas").select("id").not_.is_("condo_nome", "null").execute()
    docs = res.data or []
    print(f"Found {len(docs)} documents to update.")
    
    if docs:
        ids = [d["id"] for d in docs]
        result = supabase.table("despesas").update({"condo_nome": ""}).in_("id", ids).execute()
        print(f"Successfully updated {len(result.data)} documents.")

if __name__ == "__main__":
    run()

