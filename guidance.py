"""Optional ranking of clinician-approved guidance cards."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

TOPICS = ('after_shift', 'before_shift', 'recurring')


def configuration():
    if os.environ.get('EVVARDIA_GUIDANCE_ENABLED') != '1':
        return None
    model = os.environ['EVVARDIA_GUIDANCE_MODEL'].strip()
    key = os.environ['OPENAI_API_KEY'].strip()
    if not model or not key:
        raise ValueError('Guidance requires a model and an API key.')
    catalog = json.loads(Path(os.environ['EVVARDIA_GUIDANCE_CATALOG']).read_text(encoding='utf-8'))
    if not isinstance(catalog, dict) or set(catalog) != set(TOPICS):
        raise ValueError('Guidance catalog must contain the three study topics.')
    for cards in catalog.values():
        if not isinstance(cards, list) or not 1 <= len(cards) <= 12:
            raise ValueError('Each topic requires 1–12 approved cards.')
        for card in cards:
            if not isinstance(card, dict) or set(card) != {'today', 'next_days'} or any(
                not isinstance(value, str) or not 1 <= len(value.strip()) <= 500
                for value in card.values()
            ):
                raise ValueError('Each card requires today and next_days text.')
    return model, key, catalog


def suggest(topic, config):
    model, key, catalog = config
    cards = catalog[topic]
    payload = {
        'model': model, 'store': False,
        'instructions': 'Select the most practical approved card for the given work-wellbeing topic. Return only its zero-based integer index.',
        'input': json.dumps({'topic': topic, 'cards': cards}, ensure_ascii=False),
        'max_output_tokens': 64,
    }
    request = Request('https://api.openai.com/v1/responses', data=json.dumps(payload).encode(),
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=8) as response:
            result = json.load(response)
        texts = [part['text'].strip() for item in result['output'] if item['type'] == 'message'
                 for part in item['content'] if part['type'] == 'output_text']
        if len(texts) == 1 and texts[0] in {str(i) for i in range(len(cards))}:
            return cards[int(texts[0])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return cards[0]
