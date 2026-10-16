"""Uniform user-message processing; the legacy entry point no longer classifies text."""


def route_turn(text, recent=(), has_attachment=False):
    """Keep one processing contract for every user message and attachment."""
    return {'version': 5, 'kind': 'unified', 'reason': 'uniform_user_message_processing',
            'appraisal_mode': 'full', 'appraisal': True, 'retrieval': True}
