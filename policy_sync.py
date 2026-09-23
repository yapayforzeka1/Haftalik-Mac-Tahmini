"""Read approved configuration; never mutate the Operations source."""
from pathlib import Path
from learning import POLICIES, utcnow
from storage import StateError, load_json


def apply_approved_policy(state, filename):
    if not filename:
        return
    path = Path(filename)
    if not path.is_file():
        raise StateError('Configured Operations policy file missing.')
    doc = load_json(path, {})
    revision = doc.get('revision')
    if (doc.get('schema') != 1 or type(revision) is not int or revision < 0
            or doc.get('policy') not in POLICIES
            or doc.get('instruction') != POLICIES[doc['policy']]):
        raise StateError('Invalid approved policy; configuration unchanged.')
    if revision < state['revision']:
        raise StateError('Stale Operations revision; configuration unchanged.')
    if revision == state['revision'] and doc['policy'] != state['policy']:
        raise StateError('Conflicting Operations revision.')
    state['policy'], state['revision'] = doc['policy'], revision
    if state.get('policy_application', {}).get('revision') != revision:
        state['policy_application'] = {'revision':revision, 'policy':doc['policy'], 'applied_at':utcnow(), 'status':'APPLIED_TO_FUTURE_PREDICTIONS'}
