"""Conservative DOI normalization; never equate unrelated preprint versions."""
import re
from urllib.parse import unquote

def normalize_doi(value):
    value=unquote(str(value or '')).strip().lower()
    value=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',value)
    return value if re.fullmatch(r'10\.\d{4,9}/\S+',value) else ''

def publication_kind(source):
    return 'preprint' if source.lower() in {'arxiv','biorxiv','medrxiv'} else 'unverified'
