import os
from supabase import create_client

def migrate():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    target_id = "c2e47014-5925-43d2-a2b8-96f4e65bb79b"
    
    print(f"Updating all documents to use condominio_id = {target_id}")
    
    # We can fetch all and update or just try to update all directly.
    # Supabase might not allow update without .eq(), but .neq("id", "0") works
    res = supabase.table("documentos_fiscais").select("id").execute()
    docs = res.data or []
    print(f"Found {len(docs)} documents.")
    
    if docs:
        ids = [d["id"] for d in docs]
        result = supabase.table("documentos_fiscais").update({"condominio_id": target_id}).in_("id", ids).execute()
        print(f"Successfully updated {len(result.data)} documents.")

if __name__ == "__main__":
    migrate()
