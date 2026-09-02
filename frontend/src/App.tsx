import './App.css'
import { Routes, Route } from 'react-router-dom'
import { ClosedLoopTimelinePage } from './pages/ClosedLoopTimelinePage'
import { NodeDetailPage } from './pages/NodeDetailPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<ClosedLoopTimelinePage />} />
      <Route path="/node/:roundId/:nodeId" element={<NodeDetailPage />} />
    </Routes>
  )
}

export default App
