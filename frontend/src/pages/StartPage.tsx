import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { resetWorkflow } from '../api/liveWorkflow'

export function StartPage() {
  const navigate = useNavigate()
  const [resetState, setResetState] = useState<'resetting' | 'ready' | 'error'>('resetting')
  const [resetMessage, setResetMessage] = useState('正在清空上次运行记录并准备新的真实会话。')

  useEffect(() => {
    let active = true

    const clearClientCache = () => {
      if (typeof window === 'undefined') {
        return
      }
      window.localStorage.removeItem('st_demo_question')
      window.localStorage.removeItem('st_demo_knowledge_files')
      window.localStorage.removeItem('st_demo_data_files')
    }

    clearClientCache()

    void (async () => {
      try {
        await resetWorkflow()
        if (!active) {
          return
        }
        setResetState('ready')
        setResetMessage('当前会话已重置，可以从零开始录入科学问题并启动真实闭环。')
      } catch (error) {
        if (!active) {
          return
        }
        setResetState('error')
        setResetMessage(error instanceof Error ? error.message : '会话重置失败，请检查真实运行服务。')
      }
    })()

    return () => {
      active = false
    }
  }, [])

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--entry">
        <section className="entry-screen">
          <div className="entry-screen__brand">
            <span className="timeline-header__eyebrow">ShadowTracing</span>
            <h1>准备启动新的科研闭环</h1>
            <p>从中央控制智能体入口录入科学问题、上传知识材料与实验数据，再进入主流程工作台推进真实运行。</p>
            <div className={`timeline-empty-state${resetState === 'error' ? ' timeline-empty-state--error' : ''}`}>
              {resetMessage}
            </div>
          </div>

          <div className="entry-screen__actions">
            <button
              type="button"
              className="entry-screen__button entry-screen__button--primary"
              onClick={() => navigate('/dialogue')}
            >
              进入中央控制页
            </button>
            <button
              type="button"
              className="entry-screen__button"
              onClick={() => navigate('/workflow')}
            >
              打开主工作台
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
