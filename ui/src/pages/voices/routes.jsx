import { useLoaderData } from 'react-router';
import { queryClient } from '../../lib/queries.js';
import { VoicesList, voicesLoader } from './VoicesList.jsx';
import { VoiceDetail, voiceLoader } from './VoiceDetail.jsx';
import { CharacterProfile, characterLoader } from './CharacterProfile.jsx';
import { Knowledge, knowledgeLoader } from './Knowledge.jsx';
import './voices.css';

// /voices/character:<id> is a character's page; any other key is a catalogue
// voice, which redirects to its character once it is cast as one.
const isCharacter = key => key.startsWith('character:');

async function voiceKeyLoader(args) {
  const data = isCharacter(args.params.key) ? await characterLoader(args) : await voiceLoader(args);
  return { ...data, kind: isCharacter(args.params.key) ? 'character' : 'voice' };
}

function VoiceKey() {
  const { kind } = useLoaderData();
  return kind === 'character' ? <CharacterProfile /> : <VoiceDetail />;
}

// "<name> — Voices" in the tab, from what the loader put in the cache.
function voiceTitle(match) {
  const data = match.data || {};
  const name = data.kind === 'character'
    ? queryClient.getQueryData(['character', data.id])?.character?.name
    : (v => v && (v.display_name || v.name))(queryClient.getQueryData(['voice', data.key])?.voice);
  return name ? `${name} — Voices` : 'Voices';
}

export const routes = [
  { path: 'voices', element: <VoicesList />, loader: voicesLoader, handle: { nav: 'Voices', title: 'Voices' } },
  { path: 'voices/:key', element: <VoiceKey />, loader: voiceKeyLoader, handle: { nav: 'Voices', title: voiceTitle } },
  { path: 'knowledge', element: <Knowledge />, loader: knowledgeLoader, handle: { nav: 'Knowledge', title: 'Knowledge' } },
];
