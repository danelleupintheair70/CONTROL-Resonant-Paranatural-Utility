import { useNavigate } from 'react-router';
import { api } from './api.js';

// Open (or reopen) the studio for an episode file; the server keys it by media.
// Returns a function taking { path, title, jobId, seriesRef }.
export function useOpenStudio() {
  const navigate = useNavigate();
  return async function openStudio({ path, title, jobId = '', seriesRef = '' }) {
    try {
      const opened = await api('studio/sessions', { method: 'POST',
        json: { path, title, job_id: jobId, series_ref: seriesRef } });
      navigate(`/studio/${encodeURIComponent(opened.session.id)}/${opened.session.view || 'overview'}`);
    } catch (error) {
      window.alert(error.message);
    }
  };
}
