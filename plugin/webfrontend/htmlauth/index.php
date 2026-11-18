<?php
require_once "loxberry_system.php";
require_once "loxberry_web.php";

$at_cfgfile    = LBPCONFIGDIR . "/abholtermine.json";
// Gleicher Pfad wie STATUS_FILE in abholtermine_bridge.py (im RAM, schont die SD-Karte)
$at_statusfile = "/dev/shm/loxberry-plugin-abholtermine/status.json";
$at_flagfile   = LBPDATADIR . "/refresh.flag";
$at_logfile    = LBPLOGDIR . "/abholtermine.log";
$at_service    = LBPBINDIR . "/service.sh";

const AT_BASE = 'https://www.umweltprofis.at';
const AT_LOOKUP = '/allgemein/module/was_wie_zu_entsorgen_ist.html';

function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }

// Bezirke wie DISTRICTS in umweltprofis.py
$at_districts = [
	'2' => 'Braunau am Inn', '3' => 'Eferding', '4' => 'Freistadt', '5' => 'Gmunden', '6' => 'Grieskirchen',
	'7' => 'Kirchdorf an der Krems', '8' => 'Linz', '9' => 'Linz-Land', '10' => 'Perg', '11' => 'Ried im Innkreis',
	'12' => 'Rohrbach', '13' => 'Schärding', '14' => 'Steyr-Land', '15' => 'Steyr', '16' => 'Urfahr-Umgebung',
	'17' => 'Vöcklabruck', '18' => 'Wels', '19' => 'Wels-Land',
];

// Standardwerte – müssen DEFAULT_CONFIG in abholtermine_bridge.py und config/abholtermine.json entsprechen
$at_defaults = [
	'enabled' => true,
	'location' => [
		'district' => '', 'district_name' => '', 'city' => '', 'city_name' => '',
		'street' => '', 'street_name' => '', 'house' => '', 'house_name' => '',
	],
	'days' => 14,
	'reminder_time' => '18:00',
	'filters' => [],
	'refresh_hours' => 6,
	'topic' => 'abholtermine',
	'republish_seconds' => 300,
	'loglevel' => 'INFO',
	'mqtt' => ['use_loxberry' => true, 'host' => 'localhost', 'port' => 1883, 'user' => '', 'password' => ''],
];

// Wie slug() in termine.py
function slug($at_text) {
	$at_text = mb_strtolower((string)$at_text, 'UTF-8');
	$at_text = strtr($at_text, ['ä' => 'ae', 'ö' => 'oe', 'ü' => 'ue', 'ß' => 'ss']);
	$at_conv = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $at_text);
	if ($at_conv !== false) $at_text = $at_conv;
	$at_text = trim(preg_replace('/[^a-z0-9]+/', '_', $at_text), '_');
	return $at_text !== '' ? $at_text : 'x';
}

function read_config($at_file) {
	global $at_defaults;
	$at_cfg = json_decode(@file_get_contents($at_file), true);
	$at_cfg = is_array($at_cfg) ? $at_cfg : [];
	$at_out = array_merge($at_defaults, $at_cfg);
	foreach (['location', 'mqtt'] as $at_k) {
		$at_out[$at_k] = array_merge($at_defaults[$at_k], is_array($at_cfg[$at_k] ?? null) ? $at_cfg[$at_k] : []);
	}
	if (!is_array($at_out['filters'])) $at_out['filters'] = [];
	return $at_out;
}

function write_config($at_cfg) {
	global $at_cfgfile;
	$at_json = json_encode($at_cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
	// leere Filterliste als Objekt speichern (nicht als [])
	$at_json = preg_replace('/"filters": \[\]/', '"filters": {}', $at_json);
	$at_ok = file_put_contents($at_cfgfile, $at_json) !== false;
	@chmod($at_cfgfile, 0600);
	return $at_ok;
}

function service($at_cmd) {
	global $at_service;
	return trim((string)shell_exec(escapeshellarg($at_service) . " " . escapeshellarg($at_cmd) . " </dev/null 2>&1"));
}

function is_running() {
	return strpos(service('status'), 'running') === 0;
}

$at_L = LBSystem::readlanguage("language.ini");

function tr($at_key, ...$at_args) {
	global $at_L;
	$at_text = $at_L[$at_key] ?? $at_key;
	return $at_args ? vsprintf($at_text, $at_args) : $at_text;
}

// Übersetzter Text, HTML-escaped; %s-Argumente werden unverändert eingesetzt (vorher selbst escapen)
function t($at_key, ...$at_args) {
	$at_text = h(tr($at_key));
	return $at_args ? vsprintf($at_text, $at_args) : $at_text;
}

// ---------------------------------------------------------------- Auswahllisten (Proxy zu umweltprofis.at)
$at_ajax = $_GET['ajax'] ?? '';
$at_lookups = ['cities' => ['ajaxGetCities', 'district'], 'streets' => ['ajaxGetStreets', 'city'], 'houses' => ['ajaxGetHouseNumbers', 'street']];
if (isset($at_lookups[$at_ajax])) {
	[$at_action, $at_param] = $at_lookups[$at_ajax];
	$at_id = preg_replace('/[^0-9]/', '', $_GET['id'] ?? '');
	header('Content-Type: application/json; charset=utf-8');
	header('Cache-Control: no-store');
	if ($at_id === '') { echo '[]'; exit; }
	$at_url = AT_BASE . AT_LOOKUP . '?' . http_build_query([
		'tx_ecxumweltprofis_pi2' => ['controller' => 'Location', 'action' => $at_action, $at_param => $at_id],
	]);
	$at_ctx = stream_context_create(['http' => [
		'timeout' => 20,
		'header' => "User-Agent: Mozilla/5.0 (X11; Linux) LoxBerry-Plugin-Abholtermine\r\n",
	]]);
	$at_raw = @file_get_contents($at_url, false, $at_ctx);
	$at_list = json_decode((string)$at_raw, true);
	if (!is_array($at_list)) {
		http_response_code(502);
		echo json_encode(['error' => tr('MSG.LOOKUP_FAILED')]);
		exit;
	}
	$at_out = [];
	foreach ($at_list as $at_item) {
		if (is_array($at_item) && isset($at_item['uid'], $at_item['title'])) {
			$at_out[] = ['id' => (string)$at_item['uid'], 'name' => (string)$at_item['title']];
		}
	}
	echo json_encode($at_out, JSON_UNESCAPED_UNICODE);
	exit;
}

$at_cfg = read_config($at_cfgfile);
$at_page = (($_GET['page'] ?? '') === 'settings') ? 'settings' : 'status';
$at_message = '';
$at_message_ok = true;

// ---------------------------------------------------------------- Aktionen
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
	$at_action = $_POST['action'] ?? '';
	if ($at_action === 'save') {
		$at_page = 'settings';
		$at_cfg['enabled'] = isset($_POST['enabled']);
		$at_loc = [];
		foreach (['district', 'city', 'street', 'house'] as $at_k) {
			$at_loc[$at_k] = preg_replace('/[^0-9]/', '', $_POST["loc_$at_k"] ?? '');
			$at_loc[$at_k . '_name'] = trim(strip_tags($_POST["loc_{$at_k}_name"] ?? ''));
		}
		if ($at_loc['district'] !== '') $at_loc['district_name'] = $at_districts[$at_loc['district']] ?? $at_loc['district_name'];
		$at_cfg['location'] = $at_loc;
		$at_cfg['days'] = min(60, max(1, intval($_POST['days'] ?? 14)));
		$at_time = $_POST['reminder_time'] ?? '18:00';
		$at_cfg['reminder_time'] = preg_match('/^([01]\d|2[0-3]):[0-5]\d$/', $at_time) ? $at_time : '18:00';
		$at_filters = [];
		foreach ((array)($_POST['filter'] ?? []) as $at_name => $at_val) {
			$at_val = (string)$at_val;
			if ($at_val !== '') $at_filters[(string)$at_name] = $at_val;
		}
		$at_cfg['filters'] = $at_filters;
		$at_cfg['refresh_hours'] = min(48, max(1, intval($_POST['refresh_hours'] ?? 6)));
		$at_topic = trim(preg_replace('#[^A-Za-z0-9_/\-]#', '', $_POST['topic'] ?? 'abholtermine'), '/');
		$at_cfg['topic'] = $at_topic !== '' ? $at_topic : 'abholtermine';
		$at_cfg['republish_seconds'] = max(30, intval($_POST['republish_seconds'] ?? 300));
		$at_cfg['loglevel'] = in_array($_POST['loglevel'] ?? '', ['DEBUG', 'INFO', 'WARNING', 'ERROR']) ? $_POST['loglevel'] : 'INFO';
		$at_mqtt = $at_cfg['mqtt'];
		$at_mqtt['use_loxberry'] = isset($_POST['mqtt_use_loxberry']);
		$at_mqtt['host'] = trim($_POST['mqtt_host'] ?? 'localhost');
		$at_mqtt['port'] = intval($_POST['mqtt_port'] ?? 1883) ?: 1883;
		$at_mqtt['user'] = trim($_POST['mqtt_user'] ?? '');
		if (($_POST['mqtt_password'] ?? '') !== '') $at_mqtt['password'] = $_POST['mqtt_password'];
		$at_cfg['mqtt'] = $at_mqtt;
		if (write_config($at_cfg)) {
			service('restart');
			$at_message = tr('MSG.SAVED') . ' ' . tr(is_running() ? 'MSG.RUNNING' : 'MSG.NOT_RUNNING');
			$at_message_ok = is_running() || empty($at_cfg['enabled']);
		} else {
			[$at_message_ok, $at_message] = [false, tr('MSG.SAVE_FAILED')];
		}
	} elseif ($at_action === 'refresh') {
		@touch($at_flagfile);
		if (!is_running()) service('start');
		$at_message = tr('MSG.REFRESH_REQUESTED');
	} elseif (in_array($at_action, ['restart', 'stop'], true)) {
		service($at_action);
		$at_up = is_running();
		$at_message_ok = $at_action === 'stop' ? !$at_up : $at_up;
		$at_message = tr($at_up ? 'MSG.RUNNING' : 'MSG.NOT_RUNNING');
	}
}

$at_status = json_decode(@file_get_contents($at_statusfile), true);
$at_status = is_array($at_status) ? $at_status : [];
$at_topic  = $at_cfg['topic'];
$at_loc    = $at_cfg['location'];

function address_text($at_loc) {
	if (($at_loc['house'] ?? '') === '') return tr('UI.NO_ADDRESS');
	return trim(($at_loc['street_name'] ?? '') . ' ' . ($at_loc['house_name'] ?? '')) . ', ' . ($at_loc['city_name'] ?? '')
		. ' (' . tr('UI.DISTRICT') . ' ' . ($at_loc['district_name'] ?? '') . ')';
}

function weekday_date($at_iso) {
	$at_days = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
	$at_ts = strtotime($at_iso);
	return $at_days[(int)date('N', $at_ts) - 1] . ', ' . date('d.m.Y', $at_ts);
}

function render_live() {
	global $at_status, $at_cfg, $at_topic, $at_loc;
	$at_running = is_running();
	$at_fresh = !empty($at_status['time']) && time() - (int)$at_status['time'] < 120;
	ob_start(); ?>
	<table class="at-table">
		<tr><td><?= t('UI.SERVICE') ?></td><td><?= $at_running ? '<span class="at-ok">' . t('UI.RUNNING') . '</span>' : '<span class="at-bad">' . t('UI.STOPPED') . '</span>' ?></td></tr>
		<tr><td><?= t('UI.ADDRESS') ?></td><td><?= h(address_text($at_loc)) ?></td></tr>
		<tr><td><?= t('UI.MQTT') ?></td><td><?= $at_running && $at_fresh ? (!empty($at_status['mqtt_connected']) ? '<span class="at-ok">' . t('UI.CONNECTED') . '</span>' : '<span class="at-bad">' . t('UI.NOT_CONNECTED') . '</span>') : '–' ?> <?= h($at_status['mqtt_broker'] ?? '') ?></td></tr>
		<tr><td><?= t('UI.LAST_FETCH') ?></td><td><?= !empty($at_status['fetched']) ? h(date('d.m.Y H:i', (int)$at_status['fetched'])) : '–' ?></td></tr>
		<?php if (!empty($at_status['error'])): ?>
		<tr><td><?= t('UI.ERROR') ?></td><td class="at-bad"><?= h($at_status['error']) ?></td></tr>
		<?php endif; ?>
	</table>

	<h3><?= t('UI.UPCOMING', (int)$at_cfg['days']) ?></h3>
	<?php if (empty($at_status['entries'])): ?>
	<p class="at-hint"><?= t(empty($at_status['fetched']) ? 'UI.NO_DATA' : 'UI.NO_ENTRIES') ?></p>
	<?php else: ?>
	<table class="at-table">
		<tr><th><?= t('UI.COL_DATE') ?></th><th><?= t('UI.COL_TYPE') ?></th><th><?= t('UI.COL_INTERVAL') ?></th><th><?= t('UI.COL_IN') ?></th></tr>
		<?php foreach ($at_status['entries'] as $at_e): $at_d = (int)($at_e['days'] ?? 0); ?>
		<tr class="<?= $at_d <= 1 ? 'at-soon' : '' ?>">
			<td><?= h(weekday_date($at_e['date'])) ?></td>
			<td><?= h($at_e['type']) ?></td>
			<td><?= h($at_e['interval'] ?? '') ?></td>
			<td><?= $at_d === 0 ? t('UI.TODAY') : ($at_d === 1 ? t('UI.TOMORROW') : t('UI.IN_DAYS', $at_d)) ?></td>
		</tr>
		<?php endforeach; ?>
	</table>
	<?php endif; ?>

	<?php if (!empty($at_status['values'])): ?>
	<h3><?= t('UI.TOPICS') ?></h3>
	<table class="at-table">
		<tr><th><?= t('UI.COL_TOPIC') ?></th><th><?= t('UI.COL_VALUE') ?></th><th><?= t('UI.COL_LOXONE') ?></th></tr>
		<?php foreach ($at_status['values'] as $at_k => $at_v): ?>
		<tr>
			<td><code><?= h("$at_topic/$at_k") ?></code></td>
			<td><?= h($at_v) ?></td>
			<td class="at-hint"><code><?= h(str_replace('/', '_', "$at_topic/$at_k")) ?></code></td>
		</tr>
		<?php endforeach; ?>
	</table>
	<?php endif;
	return ob_get_clean();
}

if ($at_ajax === 'live') {
	header('Content-Type: text/html; charset=utf-8');
	header('Cache-Control: no-store');
	echo render_live();
	exit;
}

$navbar[1]['Name'] = tr('UI.NAV_STATUS');
$navbar[1]['URL'] = 'index.php';
$navbar[1]['active'] = $at_page === 'status';
$navbar[2]['Name'] = tr('UI.NAV_SETTINGS');
$navbar[2]['URL'] = 'index.php?page=settings';
$navbar[2]['active'] = $at_page === 'settings';
$navbar[3]['Name'] = tr('UI.NAV_LOG');
$navbar[3]['URL'] = '/admin/system/tools/logfile.cgi?logfile=' . urlencode($at_logfile) . '&header=html&format=template';
$navbar[3]['target'] = '_blank';

LBWeb::lbheader(tr('UI.TITLE'), "", "");
?>
<style>
	.at-ok { color: #2e7d32; font-weight: bold; }
	.at-bad { color: #c62828; font-weight: bold; }
	.at-table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
	.at-table td, .at-table th { border-bottom: 1px solid #ddd; padding: 4px 8px; text-align: left; vertical-align: top; }
	.at-table code { font-size: 90%; }
	.at-soon td { background: #fff8e1; font-weight: bold; }
	.at-hint { font-size: 90%; color: #666; }
	.at-msg { padding: 8px 12px; margin-bottom: 1em; border-radius: 4px; }
	.at-msg-ok { background: #e8f5e9; border: 1px solid #a5d6a7; color: #1b5e20; }
	.at-msg-bad { background: #fdecea; border: 1px solid #f5c6cb; color: #8a1c1c; }
</style>

<?php if ($at_message): ?><div class="at-msg <?= $at_message_ok ? 'at-msg-ok' : 'at-msg-bad' ?>"><?= h($at_message) ?></div><?php endif; ?>

<?php if ($at_page === 'status'): ?>
<h2><?= t('UI.STATUS') ?></h2>
<?php if (($at_loc['house'] ?? '') === ''): ?>
<div class="at-msg at-msg-bad"><?= t('UI.SETUP_FIRST', '<a href="index.php?page=settings">' . t('UI.NAV_SETTINGS') . '</a>') ?></div>
<?php endif; ?>
<div id="at-live"><?= render_live() ?></div>
<form method="post" action="index.php" data-ajax="false" style="display:inline">
	<button type="submit" name="action" value="refresh" data-inline="true" data-mini="true" data-icon="refresh"><?= t('UI.BTN_REFRESH') ?></button>
	<button type="submit" name="action" value="restart" data-inline="true" data-mini="true"><?= t('UI.BTN_RESTART') ?></button>
	<button type="submit" name="action" value="stop" data-inline="true" data-mini="true"><?= t('UI.BTN_STOP') ?></button>
</form>
<p class="at-hint"><?= t('UI.HINT_GATEWAY', '<code>' . h($at_topic) . '/#</code>') ?><br>
<?= t('UI.HINT_REFRESH', '<code>' . h($at_topic) . '/cmd/refresh</code>') ?></p>

<script>
(function () {
	var box = document.getElementById('at-live');
	if (!box || !window.fetch) return;
	setInterval(function () {
		if (document.hidden) return;
		fetch('index.php?ajax=live', { credentials: 'same-origin', cache: 'no-store' })
			.then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
			.then(function (html) { box.innerHTML = html; })
			.catch(function () {});
	}, 15000);
})();
</script>
<?php else: ?>
<form method="post" action="index.php?page=settings" data-ajax="false" id="at-settings">
	<input type="hidden" name="action" value="save">
	<label><input type="checkbox" name="enabled" <?= !empty($at_cfg['enabled']) ? 'checked' : '' ?>> <?= t('UI.ENABLED') ?></label>

	<h3><?= t('UI.ADDRESS') ?></h3>
	<p class="at-hint"><?= t('UI.ADDRESS_HINT') ?></p>
	<label for="loc_district"><?= t('UI.DISTRICT') ?></label>
	<select id="loc_district" name="loc_district">
		<option value=""><?= t('UI.CHOOSE') ?></option>
		<?php foreach ($at_districts as $at_id => $at_name): ?>
		<option value="<?= h($at_id) ?>" <?= (string)$at_loc['district'] === (string)$at_id ? 'selected' : '' ?>><?= h($at_name) ?></option>
		<?php endforeach; ?>
	</select>
	<?php foreach (['city' => 'UI.CITY', 'street' => 'UI.STREET', 'house' => 'UI.HOUSE'] as $at_k => $at_label): ?>
	<label for="loc_<?= $at_k ?>"><?= t($at_label) ?></label>
	<select id="loc_<?= $at_k ?>" name="loc_<?= $at_k ?>" data-current="<?= h($at_loc[$at_k]) ?>">
		<?php if ($at_loc[$at_k] !== ''): ?><option value="<?= h($at_loc[$at_k]) ?>" selected><?= h($at_loc[$at_k . '_name']) ?></option><?php endif; ?>
	</select>
	<input type="hidden" id="loc_<?= $at_k ?>_name" name="loc_<?= $at_k ?>_name" value="<?= h($at_loc[$at_k . '_name']) ?>">
	<?php endforeach; ?>
	<p class="at-hint" id="at-lookup-msg"></p>

	<h3><?= t('UI.DATES') ?></h3>
	<label for="days"><?= t('UI.DAYS') ?></label>
	<input type="number" id="days" name="days" min="1" max="60" value="<?= h($at_cfg['days']) ?>">
	<p class="at-hint"><?= t('UI.DAYS_HINT') ?></p>
	<label for="reminder_time"><?= t('UI.REMINDER_TIME') ?></label>
	<input type="time" id="reminder_time" name="reminder_time" value="<?= h($at_cfg['reminder_time']) ?>">
	<p class="at-hint"><?= t('UI.REMINDER_HINT', '<code>' . h($at_topic) . '/erinnerung</code>') ?></p>

	<h4><?= t('UI.TYPES') ?></h4>
	<?php if (empty($at_status['types'])): ?>
	<p class="at-hint"><?= t('UI.TYPES_AFTER_FETCH') ?></p>
	<?php foreach ($at_cfg['filters'] as $at_name => $at_val): ?>
	<input type="hidden" name="filter[<?= h($at_name) ?>]" value="<?= h($at_val) ?>">
	<?php endforeach; ?>
	<?php else: ?>
	<p class="at-hint"><?= t('UI.TYPES_HINT') ?></p>
	<?php foreach ($at_status['types'] as $at_type): $at_name = (string)$at_type['name']; $at_sel = (string)($at_cfg['filters'][$at_name] ?? ''); ?>
	<label for="filter_<?= h(slug($at_name)) ?>"><?= h($at_name) ?> <span class="at-hint">(<code><?= h($at_topic . '/' . slug($at_name)) ?>/…</code>)</span></label>
	<select id="filter_<?= h(slug($at_name)) ?>" name="filter[<?= h($at_name) ?>]">
		<option value="" <?= $at_sel === '' ? 'selected' : '' ?>><?= t('UI.FILTER_DEFAULT') ?><?= !empty($at_type['intervals']) ? h(' (' . $at_type['intervals'][0]['name'] . ')') : '' ?></option>
		<?php foreach ($at_type['intervals'] ?? [] as $at_iv): ?>
		<option value="<?= h($at_iv['name']) ?>" <?= $at_sel === (string)$at_iv['name'] ? 'selected' : '' ?>><?= t('UI.FILTER_ONLY', h($at_iv['name'])) ?></option>
		<?php endforeach; ?>
		<?php if (count($at_type['intervals'] ?? []) > 1): ?>
		<option value="*" <?= $at_sel === '*' ? 'selected' : '' ?>><?= t('UI.FILTER_ALL') ?></option>
		<?php endif; ?>
		<option value="-" <?= $at_sel === '-' ? 'selected' : '' ?>><?= t('UI.FILTER_NEVER') ?></option>
	</select>
	<?php endforeach; ?>
	<?php endif; ?>

	<label for="refresh_hours"><?= t('UI.REFRESH_HOURS') ?></label>
	<input type="number" id="refresh_hours" name="refresh_hours" min="1" max="48" value="<?= h($at_cfg['refresh_hours']) ?>">

	<h3><?= t('UI.MQTT') ?></h3>
	<label for="topic"><?= t('UI.BASE_TOPIC') ?></label>
	<input type="text" id="topic" name="topic" value="<?= h($at_topic) ?>">
	<label for="republish_seconds"><?= t('UI.REPUBLISH') ?></label>
	<input type="number" id="republish_seconds" name="republish_seconds" min="30" value="<?= h($at_cfg['republish_seconds']) ?>">
	<?php $at_mqtt = $at_cfg['mqtt']; $at_use_lb = !empty($at_mqtt['use_loxberry']); ?>
	<label><input type="checkbox" id="mqtt_use_loxberry" name="mqtt_use_loxberry" <?= $at_use_lb ? 'checked' : '' ?>> <?= t('UI.USE_LOXBERRY') ?></label>
	<div id="at-mqtt-manual"<?= $at_use_lb ? ' style="display:none"' : '' ?>>
	<label for="mqtt_host"><?= t('UI.BROKER_HOST') ?></label>
	<input type="text" id="mqtt_host" name="mqtt_host" value="<?= h($at_mqtt['host']) ?>">
	<label for="mqtt_port"><?= t('UI.BROKER_PORT') ?></label>
	<input type="number" id="mqtt_port" name="mqtt_port" value="<?= h($at_mqtt['port']) ?>">
	<label for="mqtt_user"><?= t('UI.BROKER_USER') ?></label>
	<input type="text" id="mqtt_user" name="mqtt_user" value="<?= h($at_mqtt['user']) ?>" autocomplete="off">
	<label for="mqtt_password"><?= t('UI.BROKER_PASSWORD') ?> <?= !empty($at_mqtt['password']) ? t('UI.PASSWORD_SAVED') : '' ?></label>
	<input type="password" id="mqtt_password" name="mqtt_password" value="" autocomplete="new-password">
	</div>

	<h3><?= t('UI.LOGGING') ?></h3>
	<select id="loglevel" name="loglevel">
		<?php foreach (['ERROR', 'WARNING', 'INFO', 'DEBUG'] as $at_lvl): ?>
		<option value="<?= $at_lvl ?>" <?= $at_cfg['loglevel'] === $at_lvl ? 'selected' : '' ?>><?= $at_lvl ?></option>
		<?php endforeach; ?>
	</select>

	<button type="submit" data-icon="check"><?= t('UI.SAVE') ?></button>
</form>

<script>
// Bezirk -> Ort -> Straße -> Hausnummer: Listen über index.php?ajax=... von umweltprofis.at laden
(function () {
	var $ = window.jQuery;
	var chain = [
		{ sel: 'loc_district' },
		{ sel: 'loc_city', ajax: 'cities' },
		{ sel: 'loc_street', ajax: 'streets' },
		{ sel: 'loc_house', ajax: 'houses' }
	];
	var msg = document.getElementById('at-lookup-msg');
	var choose = <?= json_encode(tr('UI.CHOOSE'), JSON_UNESCAPED_UNICODE) ?>;
	var loading = <?= json_encode(tr('UI.LOADING'), JSON_UNESCAPED_UNICODE) ?>;

	function el(i) { return document.getElementById(chain[i].sel); }
	function refreshWidget(s) { if ($ && $(s).selectmenu) { try { $(s).selectmenu('refresh', true); } catch (e) {} } }
	function setName(i) {
		var s = el(i), hidden = document.getElementById(chain[i].sel + '_name');
		if (hidden) hidden.value = s.selectedIndex >= 0 && s.value ? s.options[s.selectedIndex].text : '';
	}
	function clearFrom(i) {
		for (var j = i; j < chain.length; j++) {
			var s = el(j);
			s.innerHTML = '';
			s.setAttribute('data-current', '');
			setName(j);
			refreshWidget(s);
		}
	}
	function load(i, parentId, keep) {
		var s = el(i);
		if (!parentId) { clearFrom(i); return; }
		msg.textContent = loading;
		fetch('index.php?ajax=' + chain[i].ajax + '&id=' + encodeURIComponent(parentId), { credentials: 'same-origin' })
			.then(function (r) { return r.json().then(function (d) { return r.ok ? d : Promise.reject(d.error || r.status); }); })
			.then(function (items) {
				var current = keep ? s.getAttribute('data-current') : '';
				var hiddenName = document.getElementById(chain[i].sel + '_name');
				var currentName = keep && hiddenName ? hiddenName.value.trim().toLowerCase() : '';
				s.innerHTML = '<option value="">' + choose + '</option>';
				// umweltprofis.at vergibt IDs gelegentlich neu: gespeicherte ID oder sonst gleicher Name
				var match = items.filter(function (it) { return it.id === current; })[0]
					|| items.filter(function (it) { return currentName && it.name.trim().toLowerCase() === currentName; })[0];
				items.forEach(function (it) {
					var o = document.createElement('option');
					o.value = it.id; o.textContent = it.name;
					if (match && it.id === match.id) o.selected = true;
					s.appendChild(o);
				});
				if (match) s.setAttribute('data-current', match.id);
				if (items.length === 1 && !match) s.options[1].selected = true;  // z. B. Bezirk Wels: nur ein Ort
				refreshWidget(s);
				setName(i);
				msg.textContent = '';
				if (i + 1 < chain.length) load(i + 1, s.value, keep);
			})
			.catch(function (e) { msg.textContent = String(e); });
	}
	chain.forEach(function (c, i) {
		var handler = function () {
			setName(i);
			if (i + 1 < chain.length) { clearFrom(i + 1); load(i + 1, el(i).value, false); }
		};
		el(i).addEventListener('change', handler);
		if ($) $(el(i)).on('change', function (e) { if (!e.originalEvent) handler(); });
	});
	// vollständige Listen für die gespeicherte Adresse laden (Auswahl bleibt erhalten)
	if (el(0).value) load(1, el(0).value, true);
})();

// Eigene Broker-Felder nur zeigen, wenn die LoxBerry-Zugangsdaten nicht verwendet werden
(function () {
	var cb = document.getElementById('mqtt_use_loxberry');
	var box = document.getElementById('at-mqtt-manual');
	if (!cb || !box) return;
	function update() { box.style.display = cb.checked ? 'none' : ''; }
	cb.addEventListener('change', update);
	cb.addEventListener('click', function () { setTimeout(update, 0); });
	if (window.jQuery) { window.jQuery(cb).on('change', update); }
	update();
})();
</script>
<?php endif; ?>

<?php
LBWeb::lbfooter();
