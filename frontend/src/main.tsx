import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Vazirmatn, self-hosted rather than pulled from a CDN. This app handles tax
// data and often runs on a machine with no route to the public internet: a
// third-party font request would be both a privacy leak and a way for the whole
// interface to render in Tahoma the day the CDN is unreachable.
// Variable weight — one file covers 100..900, so the weights below cost nothing.
import '@fontsource-variable/vazirmatn'
import { App } from './App'
import './styles/app.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
