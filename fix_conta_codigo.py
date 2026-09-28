import os
import json
from supabase import create_client

def run():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    print("Fixing conta_codigo based on sugestao_contabil...")
    try:
        res = supabase.table("documentos_fiscais").select("id, sugestao_contabil, conta_codigo").execute()
        docs = res.data or []
        print(f"Found {len(docs)} documents.")
        updated_count = 0
        for d in docs:
            sugestao = d.get("sugestao_contabil") or {}
            # Sometimes it's a JSON string, sometimes a dict. Let's handle both safely
            if isinstance(sugestao, str):
                try:
                    sugestao = json.loads(sugestao)
                except:
                    sugestao = {}
            
            conta_deb = sugestao.get("conta_debito_codigo")
            if conta_deb:
                supabase.table("documentos_fiscais").update({"conta_codigo": conta_deb}).eq("id", d["id"]).execute()
                updated_count += 1
                
        print(f"Successfully updated {updated_count} documents with real conta_codigo.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
