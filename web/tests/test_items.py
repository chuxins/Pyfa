"""Tests for the small helpers the browser needs: item classification and
finding which fitted modules can take a charge, and the attribute panel's two
lists: the type's own values and the ones a fit makes of an item."""

from web.tests.conftest import AUTOCANNON_ID, EMP_S_ID, RIFTER_ID

HOBGOBLIN_II = 2456
DAMAGE_CONTROL_II = 2048
BLUE_PILL = 9950
NANITE_PASTE = 28668
BASIC_IMPLANT = 9943


def gun_fit(user_client, charge=False):
    """A Rifter with one 200mm AutoCannon II fitted, and where that module sits."""
    fit_id = user_client.post('/api/fits', json={'shipId': RIFTER_ID}).json()['id']
    detail = user_client.post(
        '/api/fits/{}/commands'.format(fit_id),
        json={'command': 'addLocalModule', 'args': {'itemId': AUTOCANNON_ID}}).json()
    position = next(entry['position'] for entry in detail['racks']['high']
                    if entry['itemId'] == AUTOCANNON_ID)
    if charge:
        user_client.post(
            '/api/fits/{}/commands'.format(fit_id),
            json={'command': 'changeLocalModuleCharges',
                  'args': {'positions': [position], 'chargeItemId': EMP_S_ID}})
    return fit_id, position


def test_item_kind_drives_the_ui_action(client):
    """Clicking an item has to do the right thing without hard-coding ids."""
    cases = {
        AUTOCANNON_ID: 'module',
        EMP_S_ID: 'charge',
        HOBGOBLIN_II: 'drone',
        BLUE_PILL: 'booster',
        RIFTER_ID: 'ship',
        NANITE_PASTE: 'charge',
    }
    for item_id, expected in cases.items():
        payload = client.get('/api/items/{}'.format(item_id)).json()
        assert payload['itemKind'] == expected, (payload['name'], payload['itemKind'], expected)


def test_search_results_carry_the_action_kind(client):
    results = client.get('/api/items/search', params={'q': 'EMP S'}).json()['results']
    assert results
    # "EMP S" itself is a charge, so it should be the top hit and ready to load
    assert results[0]['itemKind'] == 'charge'
    assert all(item['itemKind'] for item in results)


def test_charge_targets_match_the_fitted_module(user_client):
    fit_id = user_client.post('/api/fits', json={'shipId': RIFTER_ID}).json()['id']
    user_client.post('/api/fits/{}/commands'.format(fit_id),
                     json={'command': 'addLocalModule', 'args': {'itemId': AUTOCANNON_ID}})

    payload = user_client.get('/api/fits/{}/charge-targets'.format(fit_id),
                              params={'chargeItemId': EMP_S_ID}).json()
    assert len(payload['targets']) == 1
    assert payload['targets'][0]['itemId'] == AUTOCANNON_ID

    # A charge nothing can use yields no targets rather than an error
    other = user_client.get('/api/fits/{}/charge-targets'.format(fit_id),
                            params={'chargeItemId': 28802}).json()
    assert other['targets'] == []


def test_charge_targets_require_a_real_fit(user_client):
    response = user_client.get('/api/fits/9999/charge-targets', params={'chargeItemId': EMP_S_ID})
    assert response.status_code == 404


def test_variations_and_requirements_are_available(client):
    variations = client.get('/api/items/{}/variations'.format(AUTOCANNON_ID)).json()['variations']
    assert variations
    assert all('name' in entry and 'id' in entry for entry in variations)
    assert any(entry['id'] == DAMAGE_CONTROL_II or entry['id'] == AUTOCANNON_ID for entry in variations)


def test_attribute_rows_can_be_requested_as_modified(user_client):
    fit_id = user_client.post('/api/fits', json={'shipId': RIFTER_ID}).json()['id']
    user_client.post('/api/fits/{}/commands'.format(fit_id),
                     json={'command': 'addLocalModule', 'args': {'itemId': AUTOCANNON_ID}})
    detail = user_client.get('/api/fits/{}'.format(fit_id)).json()
    module = next(m for m in detail['racks']['high'] if m['itemId'] == AUTOCANNON_ID)

    modified = user_client.get(
        '/api/items/{}/attributes'.format(AUTOCANNON_ID),
        params={'fitId': fit_id, 'position': module['position']}).json()
    assert modified['modified'] is True
    assert modified['rows']
    # Skills are all 5 here, so the rate of fire attribute is already modified
    assert any(row['name'] == 'speed' for row in modified['rows'])


def test_a_fitted_item_names_attributes_like_the_type_list_does(user_client, monkeypatch):
    """The panel says 失准范围 whichever list an attribute came from.

    The two lists are read through different models: the type's own goes via the engine's
    ``Attribute`` wrapper, which binds ``displayName`` to one of eve.db's language columns,
    while a fitted item's is built from the attribute table itself, where ``displayName``
    stays English. Running this request as a Chinese server pins the column down instead
    of depending on the language the test session happens to use.
    """
    import eos.config

    fit_id, position = gun_fit(user_client)
    monkeypatch.setattr(eos.config, "lang", eos.config.translation_mapping["zh"])

    plain = {row['name']: row for row in user_client.get(
        '/api/items/{}/attributes'.format(AUTOCANNON_ID)).json()['rows']}
    fitted = {row['name']: row for row in user_client.get(
        '/api/items/{}/attributes'.format(AUTOCANNON_ID),
        params={'fitId': fit_id, 'position': position}).json()['rows']}

    assert fitted['falloff']['displayName'] == plain['falloff']['displayName'] == '失准范围'
    assert fitted['damageMultiplier']['displayName'] == '伤害量调整'
    # Units are translated in the same columns, and are not left on their English text
    assert plain['chargeSize']['unit'] == fitted['chargeSize']['unit']
    assert '小型' in plain['chargeSize']['unit']  # English says "1=small 2=medium 3=large"


def test_every_row_of_a_fit_can_be_read_as_the_fit_has_it(user_client):
    """A click names the row it was on, and each kind answers with that row's own values."""
    fit_id, position = gun_fit(user_client, charge=True)

    def run(command, **args):
        response = user_client.post('/api/fits/{}/commands'.format(fit_id),
                                    json={'command': command, 'args': args})
        assert response.status_code == 200, response.text

    run('addLocalDrone', itemId=HOBGOBLIN_II, amount=5)
    run('addCargo', itemId=NANITE_PASTE, amount=10)
    run('addImplant', itemId=BASIC_IMPLANT)
    run('addBooster', itemId=BLUE_PILL)

    rows = (
        (AUTOCANNON_ID, 'module', position),
        (EMP_S_ID, 'moduleCharge', position),
        (HOBGOBLIN_II, 'drone', 0),
        (NANITE_PASTE, 'cargo', 0),
        (BASIC_IMPLANT, 'implant', 0),
        (BLUE_PILL, 'booster', 0),
    )
    for item_id, kind, row in rows:
        payload = user_client.get(
            '/api/items/{}/attributes'.format(item_id),
            params={'fitId': fit_id, 'position': row, 'kind': kind}).json()
        assert payload['modified'] is True, (kind, payload)
        assert payload['rows'], (kind, payload)


def test_a_row_is_refused_rather_than_answered_with_another_rows_numbers(user_client):
    """The charge loaded in a module is not the module: asking for one must not get the other.

    This is the whole reason a click sends the kind along with the position: the module
    and its charge share a position, and both are modules only in the loose sense that one
    holds the other.
    """
    fit_id, position = gun_fit(user_client, charge=True)

    # the charge's id at a module position, and the module's id at a charge position
    assert user_client.get('/api/items/{}/attributes'.format(EMP_S_ID),
                           params={'fitId': fit_id, 'position': position}).status_code == 400
    assert user_client.get('/api/items/{}/attributes'.format(AUTOCANNON_ID),
                           params={'fitId': fit_id, 'position': position,
                                   'kind': 'moduleCharge'}).status_code == 400
    # a kind this server does not know, and a row that is not there
    assert user_client.get('/api/items/{}/attributes'.format(AUTOCANNON_ID),
                           params={'fitId': fit_id, 'position': position,
                                   'kind': 'warpdrive'}).status_code == 400
    assert user_client.get('/api/items/{}/attributes'.format(AUTOCANNON_ID),
                           params={'fitId': fit_id, 'position': 99}).status_code == 400


def test_fitted_rows_leave_out_attributes_the_game_data_does_not_name(user_client):
    """Unpublished rows would read as ``accuracyBonus`` in the middle of a fit's values.

    They have no name in the game data to show, and pyfa's own item window leaves them out
    of its normal view as well, so a fitted item's list follows the type's list in being
    published-only.
    """
    fit_id, position = gun_fit(user_client)
    names = {row['name'] for row in user_client.get(
        '/api/items/{}/attributes'.format(AUTOCANNON_ID),
        params={'fitId': fit_id, 'position': position}).json()['rows']}

    assert 'heatDamage' in names
    assert 'heatAbsorbtionRateModifier' not in names
    assert 'accuracyBonus' not in names
