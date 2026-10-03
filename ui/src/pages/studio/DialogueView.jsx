import { useEffect, useRef } from 'react';
import { queryClient } from '../../lib/queries.js';
import { Review } from '../dubs/Review.jsx';
import { NotesPanel } from './NotesPanel.jsx';

// Dialogue: the review editor embedded beside this run's notes. The open line
// drives the transport; the saved line is reopened when the review loads.
export function DialogueView({ ctrl }) {
  const review = useRef(null);
  const reopened = useRef(false);
  const job = ctrl.jobId();

  useEffect(() => {
    if (!job) return undefined;
    ctrl.attachReview({
      get data() { return review.current?.data || null; },
      focusLine: index => review.current?.focusLine(index) || false,
    });
    ctrl.loadNotes();
    return () => ctrl.attachReview(null);
  }, [ctrl, job]);

  if (!job) {
    return (
      <div className="panel studio-empty"><p>No draft has been rendered for this episode yet.
        Dialogue, takes and comparisons appear once a run finishes.</p>
        <button type="button" className="btn btn-primary" data-go="overview" onClick={() => ctrl.show('overview')}>Render a draft from Overview</button></div>
    );
  }

  // The review selects a line as soon as it loads: the first time, go to the
  // line this studio was last on instead.
  function onSelect(row) {
    if (!reopened.current) {
      reopened.current = true;
      const line = ctrl.state.session.line;
      if (line != null && line !== row.index && review.current?.focusLine(line)) return;
    }
    ctrl.onLine(row);
  }
  function onQueued(result, cues) {
    queryClient.invalidateQueries({ queryKey: ['jobs'] });
    ctrl.repairQueued(result, cues);
  }

  return (
    <>
      <div className="studio-dialogue" id="studioDialogue">
        <Review ref={review} jobId={job} embedded onSelect={onSelect} onQueued={onQueued} />
      </div>
      <NotesPanel ctrl={ctrl} />
    </>
  );
}
