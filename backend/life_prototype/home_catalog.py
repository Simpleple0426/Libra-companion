"""Complete user-authorized household configuration, separate from life facts."""
from copy import deepcopy
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name('home_catalog.json')


def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf8'))


def apply_to_world(config):
    """Add missing identities without resetting moved objects or live state."""
    result = deepcopy(config)
    data = catalog()
    source = data['source_document'] + '; ' + data['authorization']
    for group in ('places', 'objects'):
        for ident, node in data[group].items():
            result.setdefault(group, {}).setdefault(ident, {
                **deepcopy(node), 'status': 'confirmed', 'source': source})
    edges = result['household_world']['edges']
    present = {frozenset(pair) for pair in edges}
    for edge in data['edges']:
        if frozenset(edge) not in present:
            edges.append(edge)
            present.add(frozenset(edge))
        result.setdefault('edge_seconds', {}).setdefault('|'.join(sorted(edge)), 60)
    result['household_catalog'] = {
        'version': data['version'], 'source': source, 'source_tree_sha256': data['source_tree_sha256'],
        'timing': '60 seconds per new passage, inherited simulation convention, not measured geometry',
        'containment': 'parent identifies room; container_id identifies furniture/container; neither implies walls',
        'boundary': data['boundary']}
    from .config import validate
    validate(result)
    for obj in result['objects'].values():
        container = obj.get('container_id')
        if container and container not in result['objects']:
            raise ValueError('unknown household container')
    return result
