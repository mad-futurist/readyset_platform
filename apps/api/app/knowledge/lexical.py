import re


def significant_query(query: str) -> str:
    """Bounded literal alternatives; preserve quoted phrases, never expand.

    PostgreSQL's English dictionary handles function words and inflection.
    Quoting every token keeps user operators from becoming query syntax.
    The original question remains unchanged for embeddings and generation.
    """
    terms = re.findall(r'"[^"\n]+"|[^\W_]+(?:[-.][^\W_]+)*', query, flags=re.UNICODE)
    return " OR ".join(dict.fromkeys('"' + term.strip('"') + '"' for term in terms[:64]))
