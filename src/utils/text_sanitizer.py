import re

ACRONYMS = {
    "S/A", "SA", "ME", "EPP", "EIRELI", "SABESP", "PIX", "NF", "DARF",
    "CNPJ", "CPF", "MEI", "TED", "DOC", "FGTS", "INSS", "GPS", "IRRF", "ISS"
}

SPECIAL_DOC_TYPES = {
    "nfse": "NFSe",
    "nfe": "NFe",
    "danfe": "Danfe",
    "cte": "CTe",
    "ct-e": "CT-e",
    "cupom": "Cupom",
    "recibo": "Recibo",
}

PREPOSITIONS = {"de", "da", "do", "dos", "das", "em", "para", "com", "no", "na", "nos", "nas", "e"}

# Dicionário de acentuação para termos fiscais, comerciais, condominiais e gerais
DICIONARIO_ACENTOS = {
    # Casos diretos solicitados pelo usuário
    "comercio": "comércio",
    "comercios": "comércios",
    "gestao": "gestão",
    "gestoes": "gestões",
    "servico": "serviço",
    "servicos": "serviços",

    # Serviços, Manutenção, Engenharia e Obras
    "manutencao": "manutenção",
    "manutencoes": "manutenções",
    "instalacao": "instalação",
    "instalacoes": "instalações",
    "conservacao": "conservação",
    "construcao": "construção",
    "construcoes": "construções",
    "reparacao": "reparação",
    "reparacoes": "reparações",
    "operacao": "operação",
    "operacoes": "operações",
    "higienizacao": "higienização",
    "impermeabilizacao": "impermeabilização",
    "dedetizacao": "dedetização",
    "desratizacao": "desratização",
    "desentupidora": "desentupidora",
    "locacao": "locação",
    "locacoes": "locações",
    "prestacao": "prestação",
    "prestacoes": "prestações",
    "producao": "produção",
    "producoes": "produções",
    "distribuicao": "distribuição",
    "distribuicoes": "distribuições",
    "distribuidor": "distribuidor",
    "distribuidora": "distribuidora",
    "distribuidoras": "distribuidoras",
    "seguranca": "segurança",
    "segurancas": "seguranças",
    "administracao": "administração",
    "administracoes": "administrações",
    "administrador": "administrador",
    "administradora": "administradora",
    "administradoras": "administradoras",
    "vigilancia": "vigilância",
    "iluminacao": "iluminação",
    "ventilacao": "ventilação",
    "refrigeracao": "refrigeração",
    "climatizacao": "climatização",
    "automacao": "automação",
    "automacoes": "automações",
    "solucao": "solução",
    "solucoes": "soluções",
    "protecao": "proteção",
    "protecoes": "proteções",
    "prevencao": "prevenção",
    "prevencoes": "prevenções",

    # Áreas Técnicas e Fornecimentos
    "eletrica": "elétrica",
    "eletricas": "elétricas",
    "eletrico": "elétrico",
    "eletricos": "elétricos",
    "eletronica": "eletrônica",
    "eletronicas": "eletrônicas",
    "eletronico": "eletrônico",
    "eletronicos": "eletrônicos",
    "hidraulica": "hidráulica",
    "hidraulicas": "hidráulicas",
    "hidraulico": "hidráulico",
    "hidraulicos": "hidráulicos",
    "mecanica": "mecânica",
    "mecanicas": "mecânicas",
    "mecanico": "mecânico",
    "mecanicos": "mecânicos",
    "grafica": "gráfica",
    "graficas": "gráficas",
    "grafico": "gráfico",
    "graficos": "gráficos",
    "logistica": "logística",
    "logisticas": "logísticas",
    "industria": "indústria",
    "industrias": "indústrias",
    "farmacia": "farmácia",
    "farmacias": "farmácias",
    "quimica": "química",
    "quimicas": "químicas",
    "quimico": "químico",
    "quimicos": "químicos",
    "sanitaria": "sanitária",
    "sanitarias": "sanitárias",
    "sanitario": "sanitário",
    "sanitarios": "sanitários",
    "tecnica": "técnica",
    "tecnicas": "técnicas",
    "tecnico": "técnico",
    "tecnicos": "técnicos",
    "informatica": "informática",
    "telecomunicacao": "telecomunicação",
    "telecomunicacoes": "telecomunicações",
    "comunicacao": "comunicação",
    "comunicacoes": "comunicações",
    "optica": "óptica",
    "opticas": "ópticas",
    "otica": "ótica",
    "oticas": "óticas",
    "medica": "médica",
    "medicas": "médicas",
    "medico": "médico",
    "medicos": "médicos",
    "clinica": "clínica",
    "clinicas": "clínicas",

    # Contas de Consumo / Predial / Condomínio
    "agua": "água",
    "aguas": "águas",
    "gas": "gás",
    "gases": "gases",
    "energia": "energia",
    "condominio": "condomínio",
    "condominios": "condomínios",
    "edificio": "edifício",
    "edificios": "edifícios",
    "residencia": "residência",
    "residencias": "residências",
    "patrimonio": "patrimônio",
    "patrimonios": "patrimônios",
    "incendio": "incêndio",
    "incendios": "incêndios",
    "gasometro": "gasômetro",
    "hidrometro": "hidrômetro",
    "hidrometros": "hidrômetros",
    "portao": "portão",
    "portoes": "portões",
    "camera": "câmera",
    "cameras": "câmeras",
    "cacamba": "caçamba",
    "cacambas": "caçambas",

    # Financeiro, Contábil e Pessoal
    "contabil": "contábil",
    "contabeis": "contábeis",
    "salario": "salário",
    "salarios": "salários",
    "ferias": "férias",
    "rescisao": "rescisão",
    "rescisoes": "rescisões",
    "gratificacao": "gratificação",
    "gratificacoes": "gratificações",
    "indenizacao": "indenização",
    "indenizacoes": "indenizações",
    "contribuicao": "contribuição",
    "contribuicoes": "contribuições",
    "honorario": "honorário",
    "honorarios": "honorários",
    "beneficio": "benefício",
    "beneficios": "benefícios",
    "previdencia": "previdência",
    "periodo": "período",
    "periodos": "períodos",
    "relatorio": "relatório",
    "relatorios": "relatórios",
    "orcamento": "orçamento",
    "orcamentos": "orçamentos",
    "auditoria": "auditoria",
    "bancaria": "bancária",
    "bancarias": "bancárias",
    "bancario": "bancário",
    "bancarios": "bancários",
    "tarifa": "tarifa",
    "tarifas": "tarifas",
    "notificacao": "notificação",
    "notificacoes": "notificações",
    "cobranca": "cobrança",
    "cobrancas": "cobranças",
    "juridico": "jurídico",
    "juridicos": "jurídicos",
    "juridica": "jurídica",
    "juridicas": "jurídicas",
    "veiculo": "veículo",
    "veiculos": "veículos",
    "combustivel": "combustível",
    "combustiveis": "combustíveis",
    "pedagio": "pedágio",
    "pedagios": "pedágios",
    "impressao": "impressão",
    "impressoes": "impressões",
    "copia": "cópia",
    "copias": "cópias",
    "apolice": "apólice",
    "apolices": "apólices",
    "premio": "prêmio",
    "premios": "prêmios",
    "refeicao": "refeição",
    "refeicoes": "refeições",
    "alimentacao": "alimentação",
    "alimentacoes": "alimentações",
    "descartavel": "descartável",
    "descartaveis": "descartáveis",
    "cracha": "crachá",
    "crachas": "crachás",
    "associacao": "associação",
    "associacoes": "associações",
    "fundacao": "fundação",
    "fundacoes": "fundações",
    "federacao": "federação",
    "uniao": "união",
    "regiao": "região",
    "imobiliaria": "imobiliária",
    "imobiliarias": "imobiliárias",
}

def _split_punctuation(w: str) -> tuple[str, str, str]:
    """Separa pontuação inicial e final da palavra central."""
    m = re.match(r'^([^\w]*)(.*?)([^\w]*)$', w, flags=re.UNICODE)
    if not m:
        return "", w, ""
    return m.group(1), m.group(2), m.group(3)

def _aplicar_sufixos_genericos(clean_low: str) -> str:
    """Aplica regras fonéticas de terminação para palavras não mapeadas no dicionário."""
    # -cao / -coes -> -ção / -ções
    if clean_low.endswith("cao") and len(clean_low) >= 4:
        return clean_low[:-3] + "ção"
    if clean_low.endswith("coes") and len(clean_low) >= 5:
        return clean_low[:-4] + "ções"
    # -ssao / -ssoes -> -ssão / -ssões
    if clean_low.endswith("ssao") and len(clean_low) >= 5:
        return clean_low[:-4] + "ssão"
    if clean_low.endswith("ssoes") and len(clean_low) >= 6:
        return clean_low[:-5] + "ssões"
    # -sao / -soes -> -são / -sões (expansão, divisão, revisão)
    if clean_low.endswith("sao") and len(clean_low) >= 5:
        return clean_low[:-3] + "são"
    if clean_low.endswith("soes") and len(clean_low) >= 6:
        return clean_low[:-4] + "sões"
    return clean_low

def _ajustar_palavra(w: str, forcar_title: bool = False, manter_siglas: bool = True) -> str:
    if not w:
        return w
    
    prefix, clean_w, suffix = _split_punctuation(w)
    if not clean_w:
        return w

    clean_low = clean_w.lower()
    clean_up = clean_w.upper()

    # 1. Regra especial para 'Ltda'
    if clean_low in ("ltda", "ltda."):
        return prefix + "Ltda" + suffix

    # 2. Regra especial para tipos fiscais conhecidos (NFSe, Danfe, etc.)
    if clean_low in SPECIAL_DOC_TYPES:
        return prefix + SPECIAL_DOC_TYPES[clean_low] + suffix

    # 3. Siglas comerciais/fiscais (ME, EPP, PIX, etc.)
    if manter_siglas and clean_up in ACRONYMS:
        return prefix + clean_up + suffix

    # 4. Preposições mantêm minúsculas (a menos que seja explicitamente a primeira palavra em Title)
    if clean_low in PREPOSITIONS:
        if forcar_title:
            return prefix + clean_low.capitalize() + suffix
        return prefix + clean_low + suffix

    # 5. Dicionário de acentuação PT-BR
    alvo = DICIONARIO_ACENTOS.get(clean_low)
    if not alvo:
        # Tenta regras morfológicas/fonéticas
        alvo = _aplicar_sufixos_genericos(clean_low)

    # 6. Aplicação de caixa (Title Case, Lower ou Upper)
    if forcar_title:
        resultado = alvo.capitalize()
    elif clean_w.isupper() and len(clean_w) > 3:
        # Se veio tudo em caixa alta, formata com a primeira maiúscula
        resultado = alvo.capitalize()
    elif clean_w[0].isupper():
        resultado = alvo[0].upper() + (alvo[1:] if len(alvo) > 1 else "")
    else:
        resultado = alvo.lower()

    return prefix + resultado + suffix

def sanitize_nome_fornecedor(text: str | None) -> str | None:
    """
    Higieniza o nome do fornecedor:
    - Title Case obrigatório
    - Preposições em minúsculas
    - Siglas em maiúsculas (exceto 'Ltda')
    - Correção estrita de acentuação e cedilha PT-BR
    """
    if not text or not str(text).strip():
        return text
    text_str = str(text).strip()

    words = text_str.split()
    result = []
    for i, w in enumerate(words):
        # A primeira palavra do nome sempre começa maiúscula mesmo que pareça preposição
        is_first = (i == 0)
        prefix, clean_w, suffix = _split_punctuation(w)
        if clean_w.lower() in PREPOSITIONS and not is_first:
            result.append(prefix + clean_w.lower() + suffix)
        else:
            result.append(_ajustar_palavra(w, forcar_title=True, manter_siglas=True))
            
    return " ".join(result)

def sanitize_descricao(text: str | None) -> str | None:
    """
    Higieniza a descrição da despesa:
    - Sentence Case geral (primeira palavra maiúscula)
    - Preserva nomes próprios e termos em Title Case
    - Converte 'Danfe' e 'NFSe' adequadamente
    - Garante acentuação e cedilha PT-BR (Comércio, Gestão, Serviços, etc.)
    - Formata 'Ltda' corretamente
    """
    if not text or not str(text).strip():
        return text
    text_str = str(text).strip()
    is_all_caps = text_str.isupper()

    words = text_str.split()
    result = []
    for i, w in enumerate(words):
        is_first = (i == 0)
        if is_all_caps:
            # Se a string inteira veio em CAIXA ALTA, rebaixa para Sentence Case
            # mantendo primeira palavra em Title Case e siglas preservadas
            palavra_ajustada = _ajustar_palavra(w, forcar_title=is_first, manter_siglas=True)
            result.append(palavra_ajustada)
        else:
            # Se já veio em formato de frase / mista do Gemini, apenas corrige acentuações e siglas
            prefix, clean_w, suffix = _split_punctuation(w)
            if clean_w.lower() in PREPOSITIONS and not is_first:
                result.append(prefix + clean_w.lower() + suffix)
            else:
                palavra_ajustada = _ajustar_palavra(w, forcar_title=(clean_w[0].isupper() if clean_w else False), manter_siglas=True)
                result.append(palavra_ajustada)

    return " ".join(result)
