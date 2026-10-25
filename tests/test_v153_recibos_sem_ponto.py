import pytest
from src.utils.text_sanitizer import sanitize_descricao, limpar_documento_sem_numero

def test_limpar_documento_sem_numero_conf_recibo():
    # Deve converter 'conf. recibo.' ou 'conf recibo' para 'conf. recibo' (sem ponto no final)
    assert limpar_documento_sem_numero("José Silva ref. pintura conf. recibo.") == "José Silva ref. pintura conf. recibo"
    assert limpar_documento_sem_numero("José Silva ref. pintura conf. recibo") == "José Silva ref. pintura conf. recibo"
    assert limpar_documento_sem_numero("José Silva ref. pintura conf recibo") == "José Silva ref. pintura conf. recibo"
    assert limpar_documento_sem_numero("José Silva ref. pintura CONF. RECIBO.") == "José Silva ref. pintura conf. recibo"

def test_sanitize_descricao_conf_recibo_sem_ponto():
    # Recibos devem terminar com 'conf. recibo' sem ponto final
    res = sanitize_descricao("José Silva ref. pintura conf. recibo.")
    assert res == "José Silva ref. pintura conf. recibo"
    assert not res.endswith(".")

def test_sanitize_descricao_remove_ponto_final_residual():
    # Frases normais não devem terminar com ponto final
    res1 = sanitize_descricao("Compra de materiais elétricos.")
    assert res1 == "Compra de materiais elétricos"
    assert not res1.endswith(".")

    res2 = sanitize_descricao("Manutenção de bombas d'água...")
    assert not res2.endswith(".")

def test_sanitize_descricao_preserva_sufixo_empresarial():
    # Sufixos empresariais legítimos devem manter o ponto final
    res_sa = sanitize_descricao("Light Serviços de Eletricidade S.A.")
    assert res_sa.endswith("S.A.")

    res_sa_barra = sanitize_descricao("Empresa Telefônica S/A.")
    assert res_sa_barra.endswith("S.A.")

    res_inc = sanitize_descricao("Apple Operations Inc.")
    assert res_inc.endswith("Inc.")

    res_cia = sanitize_descricao("Companhia de Saneamento Cia.")
    assert res_cia.endswith("Cia.")
