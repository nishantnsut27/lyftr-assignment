import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { createSessionId } from './session';
import './styles.css';

// Created once per page load, rather than on render or in persistent browser storage.
const sessionId = createSessionId();
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App sessionId={sessionId} />
  </StrictMode>,
);
