// Pure modules shared with the vanilla UI until cutover (docs/react-migration.md).
// Import them through here so the move at cutover touches one file.
export { api, apiUrl } from '../../../web/js/api.js';
export { safeGet, safeSet } from '../../../web/js/dom.js';
export { hardwareSummary, hardwareDetails } from '../../../web/js/hardware.js';
export { nudgeDue, REPO_URL } from '../../../web/js/star.js';
export { languageName, loadLanguages, targetChoices } from '../../../web/js/languages.js';
export { TABS, FIELD_BY_KEY, PLAN_FIELDS, isBoolField, applyDeviceOptions } from '../../../web/js/settings-model.js';
export { parseTitlePath, resolveTitleTab, titlePath } from '../../../web/js/title-routing.js';
export { castParams, jobsFor } from '../../../web/js/identity.js';
export { scopeOptions, baseOf } from '../../../web/js/knowledge-correction.js';
export { ORDERS, defaultOrder, orderRows } from '../../../web/js/review-order.js';
export { formatTime, reelLayout, locate } from '../../../web/js/media-player.js';
export { fold, distance, pickerOptions } from '../../../web/js/character-picker.js';
export { videoUrl, frameUrl, castOf, pickFrames, trackLabel } from '../../../web/js/episode-analysis.js';
export { whyText, weak } from '../../../web/js/episode-evidence.js';
export { lighten, palette, seedOf, seriesOfShow, showOfSeries, voiceFor, characterFor, SAMPLE } from '../../../web/js/voice-common.js';
export { entriesQuery, pageCount } from '../../../web/js/knowledge.js';
export { anchorsText } from '../../../web/js/audio-templates.js';
export { SOURCES, createScenePlayer } from '../../../web/js/scene-player.js';
export { FILTERS, matchesFilter } from '../../../web/js/review-scene.js';
