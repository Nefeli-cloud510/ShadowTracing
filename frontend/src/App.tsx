import './App.css'
import { StartPage } from './pages/StartPage'
import { ClosedLoopTimelinePage } from './pages/ClosedLoopTimelinePage'
import { GovernanceDecisionsPage } from './pages/GovernanceDecisionsPage'
import { MissionPage } from './pages/MissionPage'
import { NodeDetailPage } from './pages/NodeDetailPage'
import { RoundReportPage } from './pages/RoundReportPage'
import { ExecutionPage } from './pages/ExecutionPage'
import { HypothesisPage } from './pages/HypothesisPage'
import { UncertaintyPage } from './pages/UncertaintyPage'
import { DataDictionaryConfigPage } from './pages/DataDictionaryConfigPage'
import { Routes, Route, useParams } from 'react-router-dom'

function NodeDetailRoute() {
  const { roundId, nodeId } = useParams()

  if (!roundId || !nodeId) {
    return <ClosedLoopTimelinePage />
  }

  return <NodeDetailPage roundId={roundId} nodeId={nodeId} />
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<StartPage />} />
      <Route path="/workflow" element={<ClosedLoopTimelinePage />} />
      <Route path="/dialogue" element={<MissionPage />} />
      <Route path="/data-dictionary" element={<DataDictionaryConfigPage />} />
      <Route path="/hypotheses" element={<HypothesisPage />} />
      <Route path="/uncertainties" element={<UncertaintyPage />} />
      <Route path="/approval" element={<GovernanceDecisionsPage />} />
      <Route path="/execution" element={<ExecutionPage />} />
      <Route path="/report" element={<RoundReportPage />} />
      <Route path="/node/:roundId/:nodeId" element={<NodeDetailRoute />} />
    </Routes>
  )
}

export default App
