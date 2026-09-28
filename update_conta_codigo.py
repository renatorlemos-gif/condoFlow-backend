import os
from supabase import create_client

def run():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    print("Updating conta_codigo to 425 for existing documents...")
    try:
        # Fetch docs
        res = supabase.table("documentos_fiscais").select("id").execute()
        docs = res.data or []
        print(f"Found {len(docs)} documents.")
        if docs:
            ids = [d["id"] for d in docs]
            result = supabase.table("documentos_fiscais").update({"conta_codigo": "425"}).in_("id", ids).execute()
            print(f"Successfully updated {len(result.data)} documents.")
    except Exception as e:
        print(f"Error: {e}")
        print("\n\nIMPORTANT: The column 'conta_codigo' does not exist yet. Please run the SQL script provided in the artifacts in the Supabase SQL Editor FIRST, then run this python script again!")

if __name__ == "__main__":
    run()
