import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { offlineStorage } from './services/offlineStorage'

// Register Service Worker for Offline App Shell
if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then((registration) => {
      console.log('Field-to-Record ServiceWorker registered with scope:', registration.scope);
      // Attempt to request storage persistence to prevent browser eviction
      offlineStorage.requestStoragePersistence();
    }).catch((err) => {
      console.warn('ServiceWorker registration failed:', err);
    });
  });
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
