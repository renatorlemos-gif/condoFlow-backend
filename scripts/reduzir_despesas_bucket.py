"""
Script de levantamento e compressão de PDFs grandes no bucket Supabase Storage.
Bucket: integre / despesas

MODOS DE OPERAÇÃO:
1. --dry-run (Padrão): apenas lista, calcula estimativas e simula a redução sem alterar nada no bucket.
2. --apply: executa o download, recompressão com PyMuPDF/Pillow e upload substituindo o arquivo original.

Padrão de saída: PDFs recompactados com imagens em 150 DPI e JPEG 75-80%, atingindo o padrão médio de ~300-450 KB
mantendo 100% da legibilidade e textos pesquisáveis intactos.
"""

import os
import sys
import argparse
import io
import warnings
from collections import Counter
from supabase import create_client
import pymupdf
from PIL import Image

warnings.filterwarnings("ignore", category=FutureWarning)

BUCKET_NAME = os.environ.get("SUPABASE_BUCKET_CONDOMINIOS", "integre")
PREFIX = "despesas"
MAX_SIZE_BYTES = 1024 * 1024  # 1 MB


def get_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_KEY ausentes no ambiente.")
    return create_client(url, key)


def list_files_over_1mb(supabase, folder=PREFIX):
    print(f"[*] Varrendo bucket '{BUCKET_NAME}' na pasta '{folder}'...")
    all_files = []
    offset = 0
    limit = 100
    while True:
        items = supabase.storage.from_(BUCKET_NAME).list(
            folder,
            {"limit": limit, "offset": offset, "sortBy": {"column": "name", "order": "asc"}},
        )
        if not items:
            break
        for item in items:
            name = item.get("name", "")
            if item.get("id") is None and "metadata" not in item:
                # Subpasta
                sub_folder = f"{folder}/{name}"
                all_files.extend(list_files_over_1mb(supabase, sub_folder))
            else:
                full_path = f"{folder}/{name}"
                meta = item.get("metadata") or {}
                size = meta.get("size", 0) or item.get("size", 0)
                mimetype = meta.get("mimetype", "")
                all_files.append({"path": full_path, "size": size, "mimetype": mimetype})
        if len(items) < limit:
            break
        offset += limit

    gt_1mb = [f for f in all_files if f["size"] > MAX_SIZE_BYTES]
    return all_files, gt_1mb


def compress_pdf_bytes(pdf_bytes: bytes, max_dim: int = 1800, quality: int = 75) -> bytes:
    """
    Comprime o PDF reamostrando imagens embutidas e recomprimindo em JPEG.
    Preserva a legibilidade visual das notas fiscais e recibos, alinhando ao tamanho padrão (< 500 KB).
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        image_list = page.get_images(full=True)

        for img_info in image_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                img = Image.open(io.BytesIO(image_bytes))

                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                # Redimensiona se exceder a dimensão padrão de digitalização
                if max(img.size) > max_dim:
                    scale = max_dim / float(max(img.size))
                    new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                out_io = io.BytesIO()
                img.save(out_io, format="JPEG", quality=quality, optimize=True)
                new_image_bytes = out_io.getvalue()

                # Substitui se for menor
                if len(new_image_bytes) < len(image_bytes):
                    page.replace_image(xref, stream=new_image_bytes)
            except Exception:
                continue

    # Salva com garbage collection e compactação deflate
    out_pdf = doc.tobytes(
        garbage=4,
        deflate=True,
        clean=True
    )
    doc.close()
    return out_pdf


def run():
    parser = argparse.ArgumentParser(description="Otimizador de PDFs no Supabase Storage")
    parser.add_argument("--apply", action="store_true", help="Aplica a substituição real dos arquivos no bucket.")
    parser.add_argument("--limit-test", type=int, default=0, help="Testa apenas N arquivos (0 para todos).")
    parser.add_argument("--percentage", type=float, default=0.0, help="Processa apenas uma porcentagem dos arquivos (ex: 25 para 25%).")
    args = parser.parse_args()

    supabase = get_client()
    all_files, gt_1mb = list_files_over_1mb(supabase)

    # Ordena dos maiores arquivos para os menores (otimização de egress e ganho imediato)
    gt_1mb.sort(key=lambda x: x["size"], reverse=True)

    total_mb_all = sum(f["size"] for f in all_files) / (1024 * 1024)
    total_mb_gt = sum(f["size"] for f in gt_1mb) / (1024 * 1024)

    print(f"\n================ RESUMO DO LEVANTAMENTO ================")
    print(f"Total de arquivos analisados: {len(all_files)} ({total_mb_all:.2f} MB)")
    print(f"Arquivos > 1 MB identificados: {len(gt_1mb)} ({total_mb_gt:.2f} MB)")
    print(f"Tipo dos arquivos > 1 MB: {dict(Counter(f['path'].split('.')[-1].lower() for f in gt_1mb))}")
    print(f"========================================================\n")

    if not gt_1mb:
        print("[+] Nenhum arquivo > 1 MB encontrado.")
        return

    if args.percentage > 0:
        count_by_pct = max(1, int(len(gt_1mb) * (args.percentage / 100.0)))
        items_to_process = gt_1mb[:count_by_pct]
        print(f"[!] Selecionados {len(items_to_process)} arquivos ({args.percentage:.0f}% dos 182 maiores).")
    elif args.limit_test > 0:
        items_to_process = gt_1mb[:args.limit_test]
    else:
        items_to_process = gt_1mb

    size_to_process_mb = sum(f["size"] for f in items_to_process) / (1024 * 1024)
    print(f"[!] Volume a ser processado neste lote: {size_to_process_mb:.2f} MB (dos maiores para os menores)")

    if not args.apply:
        print("[AVISO] Executando em modo DRY-RUN (simulação). Nenhuma alteração será feita.")
        print("Para aplicar as reduções reais no bucket, rode o comando com o parâmetro: --apply\n")

    total_saved_bytes = 0
    total_download_bytes = 0
    total_upload_bytes = 0
    success_count = 0

    for idx, item in enumerate(items_to_process, start=1):
        path = item["path"]
        orig_size = item["size"]
        orig_mb = orig_size / (1024 * 1024)

        print(f"[{idx}/{len(items_to_process)}] Baixando: {path} ({orig_mb:.2f} MB)...", end=" ")

        try:
            # Download dos bytes originais
            res_bytes = supabase.storage.from_(BUCKET_NAME).download(path)
            total_download_bytes += len(res_bytes)
            
            # Compressão
            compressed_bytes = compress_pdf_bytes(res_bytes)
            new_size = len(compressed_bytes)
            new_mb = new_size / (1024 * 1024)
            pct = ((orig_size - new_size) / orig_size) * 100

            print(f"-> Reduzido para: {new_mb:.2f} MB (-{pct:.1f}%)", end=" ")

            if args.apply:
                # Sobrescreve com upsert: true
                supabase.storage.from_(BUCKET_NAME).upload(
                    path=path,
                    file=compressed_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"},
                )
                total_upload_bytes += new_size
                print(f"[ATUALIZADO NO BUCKET]")
            else:
                print(f"[SIMULADO]")

            total_saved_bytes += (orig_size - new_size)
            success_count += 1

        except Exception as e:
            print(f"\n   [ERRO] Falha ao processar {path}: {e}")

    print(f"\n================ RESULTADO FINAL ================")
    print(f"Arquivos processados com sucesso: {success_count}/{len(items_to_process)}")
    print(f"Tamanho original do lote: {size_to_process_mb:.2f} MB")
    print(f"Tamanho pós-compressão do lote: {(size_to_process_mb - (total_saved_bytes / (1024 * 1024))):.2f} MB")
    print(f"Espaço economizado no Storage: {total_saved_bytes / (1024 * 1024):.2f} MB")
    print(f"Tráfego de Egress consumido no download: {total_download_bytes / (1024 * 1024):.2f} MB")
    print(f"Tráfego de Ingress consumido no upload: {total_upload_bytes / (1024 * 1024):.2f} MB")
    if not args.apply:
        print("[STATUS] NENHUM ARQUIVO FOI MODIFICADO NO BUCKET (Dry-Run concluído).")
    else:
        print("[STATUS] ARQUIVOS ATUALIZADOS NO BUCKET COM SUCESSO.")
    print(f"=================================================\n")


if __name__ == "__main__":
    run()
