"""Counterfactuals are executable proofs under explicitly changed constraints."""
from app.optimizer import search, verify_plan, dt
from app.schemas import Constraints


def verified_suggestions(network, c, plans):
    suggestions = []

    def add(kind, patch, label, goal=None):
        probe = Constraints.model_validate({**c.model_dump(), **patch, **({'optimization_goal':goal} if goal else {})})
        found, _, _ = search(network, probe)
        if not found: return
        p = found[0]
        changes = dict(patch)
        if kind == 'budget': changes['max_budget_cents'] = p['total_cost_cents']
        if kind == 'deadline': changes['delivery_deadline'] = p['arrival_at']
        actual = Constraints.model_validate({**c.model_dump(), **changes})
        verify_plan(p, network, actual)
        suggestions.append({'kind':kind,'changes':changes,'summary':label(p), 'plan':p,'verified':True})

    if not plans:
        if c.max_budget_cents is not None:
            add('budget',{'max_budget_cents':None},lambda p: f"Raise the budget to ${p['total_cost_cents']/100:,.2f} (+${(p['total_cost_cents']-c.max_budget_cents)/100:,.2f}); all other hard constraints remain satisfied.",goal='cheapest')
        if c.delivery_deadline is not None:
            add('deadline',{'delivery_deadline':None},lambda p: f"Allow delivery by {p['arrival_at']}; all other hard constraints remain satisfied.",goal='fastest')
        for stops in range(c.max_stops+1,3):
            before=len(suggestions)
            add('stops',{'max_stops':stops},lambda p:f"Allow {p['leg_count']-1} intermediate stops; all other hard constraints remain satisfied.")
            if len(suggestions)>before: break
    elif c.optimization_goal == 'cheapest':
        fastest,_,_=search(network,c.model_copy(update={'optimization_goal':'fastest'}))
        if fastest and dt(fastest[0]['arrival_at']) < dt(plans[0]['arrival_at']):
            add('faster',{'optimization_goal':'fastest'},lambda p:f"Choose fastest for arrival at {p['arrival_at']} and ${p['total_cost_cents']/100:,.2f}, within the existing hard constraints.")
    return suggestions[:3]
