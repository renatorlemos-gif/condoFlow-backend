import re

ACRONYMS = {"LTDA", "S/A", "SA", "ME", "EPP", "EIRELI", "SABESP", "PIX", "NF", "DARF", "CNPJ", "CPF", "MEI", "TED", "DOC"}
PREPOSITIONS = {"de", "da", "do", "dos", "das", "em", "para", "com", "no", "na", "nos", "nas"}

def _clean_word_for_check(w: str) -> str:
    return re.sub(r'[\.,;:]+$', '', w)

def sanitize_nome_fornecedor(text: str | None) -> str | None:
    if not text or not str(text).strip():
        return text
    text_str = str(text).strip()
    
    words = text_str.split()
    result = []
    for w in words:
        w_clean_check = _clean_word_for_check(w).upper()
        if w_clean_check in ACRONYMS:
            # Mantém a formatação da sigla maiúscula, preservando a pontuação original
            # Para manter a pontuação, pegamos a sigla em maiúsculo + a pontuação final
            suffix = w[len(w_clean_check):]
            result.append(w_clean_check + suffix)
        elif w_clean_check.lower() in PREPOSITIONS:
            result.append(w.lower())
        else:
            result.append(w.capitalize())
    return " ".join(result)

def sanitize_descricao(text: str | None) -> str | None:
    if not text or not str(text).strip():
        return text
    text_str = str(text).strip()
    
    words = text_str.split()
    result = []
    for i, w in enumerate(words):
        w_clean_check = _clean_word_for_check(w).upper()
        if w_clean_check in ACRONYMS:
            suffix = w[len(w_clean_check):]
            result.append(w_clean_check + suffix)
        else:
            if i == 0:
                result.append(w.capitalize())
            else:
                result.append(w.lower())
    return " ".join(result)
