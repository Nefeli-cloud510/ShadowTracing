import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { TabProvider } from './contexts/TabContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <TabProvider>
        <App />
      </TabProvider>
    </BrowserRouter>
  </StrictMode>
)
