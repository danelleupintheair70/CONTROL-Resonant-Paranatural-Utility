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
