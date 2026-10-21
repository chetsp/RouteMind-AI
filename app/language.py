"""Conservative normalization and explicit conversational operations.

These operations never manufacture schedules or silently relax a hard constraint.
The language-model parser emits the same operations as the offline parser.
"""
import re
from datetime import timedelta
from decimal import Decimal

ONES = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20,100,10)))
WORDS = "|".join([*ONES,*TENS,"hundred","thousand","and"])
NUMBER = rf"(?:{WORDS})(?:[ -]+(?:{WORDS}))*"


def number(text):
    current, total = 0, 0
    for token in text.replace('-', ' ').split():
        if token in ONES: current += ONES[token]
        elif token in TENS: current += TENS[token]
        elif token == 'hundred': current = (current or 1)*100
        elif token == 'thousand': total += (current or 1)*1000; current = 0
    return total+current


def normalize_language(message):
    text = message.lower()
    text = re.sub(r'\bhalf (?:a )?dozen\b','6',text)
    text = re.sub(rf'\b({NUMBER})\s+dozen\b',lambda m:str(number(m[1])*12),text)
    text = re.sub(r'\b(\d+)\s+dozen\b',lambda m:str(int(m[1])*12),text)
    text = re.sub(r'\b(?:a\s+)?dozen\b', '12', text)
    text = re.sub(r'\b(?:a\s+)?couple(?:\s+of)?\b', '2', text)
    text = re.sub(rf'\b({NUMBER})\s+grand\b', lambda m: '$'+str(number(m[1])*1000), text)
    text = re.sub(r'(?<!\w)\$?(\d+(?:\.\d+)?)\s*(?:grand|k)\b', lambda m: '$'+str(int(Decimal(m[1])*1000)), text)
    text = re.sub(rf'\b({NUMBER})\s+(?:dollars|bucks)\b', lambda m: '$'+str(number(m[1])), text)
    text = re.sub(r'\b(\d+(?:\.\d{1,2})?)\s+(?:dollars|bucks)\b',r'$\1',text)
    text = re.sub(rf'\b({NUMBER})\s+percent\b',lambda m:str(number(m[1]))+'%',text)
    text = re.sub(r'\b(\d+(?:\.\d+)?)\s+percent\b',r'\1%',text)
    text = re.sub(rf'\b({NUMBER})\s+(pallets?|stops?|transfers?)\b', lambda m: str(number(m[1]))+' '+m[2], text)
    return text


def context_operations(text):
    """Return only explicitly recognized edits, not inferred user intent."""
    fields = {}
    amount = r'\$\s*([\d,]+(?:\.\d{1,2})?)'
    cents = lambda s: int(Decimal(s.replace(',', ''))*100)
    extra = re.search(r'(?:more than|up to|at most|within|by)\s*'+amount+r'\s*(?:extra|more|additional)', text)
    if extra: fields['max_extra_cost_cents'] = cents(extra[1])
    delta = re.search(r'\b(increase|raise|reduce|lower|decrease)\s+(?:the\s+)?budget\s+by\s*'+amount, text)
    if delta:
        fields['budget_delta_cents'] = cents(delta[2]) * (-1 if delta[1] in {'reduce','lower','decrease'} else 1)
    if re.search(r'\b(?:arrive|deliver|get there)\s+earlier\b', text):
        fields['arrive_earlier'] = True
    for pattern, field in [(r'\b(?:remove|drop|no)\s+(?:the\s+)?budget(?:\s+(?:limit|ceiling|cap))?\b', 'max_budget_cents'),
        (r'\b(?:remove|drop)\s+(?:the\s+)?(?:deadline|delivery deadline)\b', 'delivery_deadline'),
        (r'\b(?:remove|drop)\s+(?:the\s+)?reliability(?:\s+requirement)?\b', 'min_on_time_rate')]:
        if re.search(pattern,text): fields[field] = None
    removed=[]
    for cap,word in {'fragile':r'fragile','secure':r'secure','refrigerated':r'refrigerat(?:ed|ion)','hazmat':r'(?:hazmat|hazardous)'}.items():
        if re.search(r'\b(?:not|no|without|remove|drop)\s+(?:the\s+)?'+word+r'\b',text): removed.append(cap)
    if removed: fields['remove_capabilities']=removed
    return fields


def resolve_operations(fields, previous, baseline):
    fields = dict(fields)
    questions, assumptions = [], []
    extra = fields.pop('max_extra_cost_cents', None)
    delta = fields.pop('budget_delta_cents', None)
    earlier = fields.pop('arrive_earlier', False)
    removed = fields.pop('remove_capabilities', [])
    if 'required_capabilities' in fields or removed:
        fields['required_capabilities'] = sorted((set(previous.get('required_capabilities') or []) | set(fields.get('required_capabilities') or []))-set(removed))
    if extra is not None:
        if not baseline:
            questions.append('A verified previous plan is required to interpret an extra-cost limit. Set an absolute budget.')
        else:
            cap = baseline['total_cost_cents'] + extra
            existing = fields.get('max_budget_cents', previous.get('max_budget_cents'))
            if existing is not None: cap = min(cap,existing)
            fields['max_budget_cents'] = cap
            assumptions.append('Extra spending is measured from the previous recommended plan; the existing budget ceiling still applies.')
    if delta is not None:
        budget = previous.get('max_budget_cents')
        if budget is None or budget+delta < 0:
            questions.append('Set an absolute budget; there is no valid existing budget ceiling to adjust.')
        elif extra is not None or 'max_budget_cents' in fields:
            questions.append('Specify one budget change: an absolute ceiling, a budget adjustment, or an extra-cost limit.')
        else: fields['max_budget_cents'] = budget+delta
    if earlier:
        if not baseline:
            questions.append('A verified previous plan is required for earlier arrival. Set an explicit delivery deadline.')
        else:
            from app.optimizer import dt
            limit = dt(baseline['arrival_at'])-timedelta(seconds=1)
            existing = fields.get('delivery_deadline', previous.get('delivery_deadline'))
            if existing: limit = min(limit,dt(existing) if isinstance(existing,str) else existing)
            fields['delivery_deadline'] = limit.isoformat()
            fields['optimization_goal'] = 'fastest'
            assumptions.append('Earlier arrival means strictly before the previous recommended arrival time.')
    return fields, questions, assumptions
