import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import './App.css'

function App() {
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:8000')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState('')
  const [tokenStatus, setTokenStatus] = useState('Not connected')
  const [machineId, setMachineId] = useState('CAB-INS02')
  const [timestamp, setTimestamp] = useState('')
  const [featuresJson, setFeaturesJson] = useState(
    JSON.stringify(
      [
        {
          machine_id: 'CAB-INS02',
          timestamp: '2026-03-20T10:00:00Z',
          features: {
            pvc_screw_pressure_bar: 145.2,
            color_screw_pressure_bar: 132.8,
            nylon_screw_pressure_bar: 128.4,
            pvc_screw_speed_rpm: 310,
            color_screw_speed_rpm: 295,
            nylon_screw_speed_rpm: 280,
            motor_load_amps: 12.4,
            motor_load_percent: 68.5,
            line_speed_m_min: 42.7,
            payoff_tension_n: 220,
            takeup_tension_n: 215,
            post_extrusion_diameter_mm: 8.2,
            machine_status: 1,
          },
        },
        {
          machine_id: 'CAB-INS02',
          timestamp: '2026-03-20T10:00:10Z',
          features: {
            pvc_screw_pressure_bar: 146.0,
            color_screw_pressure_bar: 133.1,
            nylon_screw_pressure_bar: 129.0,
            pvc_screw_speed_rpm: 311,
            color_screw_speed_rpm: 296,
            nylon_screw_speed_rpm: 281,
            motor_load_amps: 12.5,
            motor_load_percent: 69.0,
            line_speed_m_min: 42.8,
            payoff_tension_n: 221,
            takeup_tension_n: 216,
            post_extrusion_diameter_mm: 8.21,
            machine_status: 1,
          },
        },
      ],
      null,
      2
    )
  )
  const [response, setResponse] = useState([])
  const [payload, setPayload] = useState([])
  const [selectedIndex, setSelectedIndex] = useState(null)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('predict')
  const [paramVisibility, setParamVisibility] = useState({})
  const [warmupActive, setWarmupActive] = useState(false)
  const chartRef = useRef(null)
  const chartInstanceRef = useRef(null)
  const corrChartRef = useRef(null)
  const corrChartInstanceRef = useRef(null)
  const matrixChartRef = useRef(null)
  const matrixChartInstanceRef = useRef(null)

  useEffect(() => {
    setTimestamp(new Date().toISOString())
  }, [])

  const latestIndex =
    selectedIndex !== null
      ? selectedIndex
      : response.length
        ? response.length - 1
        : null
  const latest = latestIndex !== null ? response?.[latestIndex] : null
  const riskPercent = useMemo(() => {
    const score =
      latest?.calibrated_risk_score ??
      latest?.risk_score ??
      0
    if (score === null || score === undefined) return 0
    return Math.round(score * 100)
  }, [latest])

  const requestToken = async () => {
    setError('')
    setTokenStatus('Connecting...')
    try {
      const body = new URLSearchParams()
      body.append('username', username)
      body.append('password', password)
      const res = await fetch(`${baseUrl}/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      })
      if (!res.ok) {
        throw new Error(`Token request failed (${res.status})`)
      }
      const data = await res.json()
      setToken(data.access_token)
      setTokenStatus('Connected')
    } catch (err) {
      setToken('')
      setTokenStatus('Not connected')
      setError(err.message)
    }
  }

  const sendPrediction = async () => {
    setError('')
    try {
      let payload = []
      if (featuresJson.trim()) {
        payload = JSON.parse(featuresJson)
      }
      setPayload(payload)
      setSelectedIndex(null)
      const res = await fetch(`${baseUrl}/api/v1/predict/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        throw new Error(`Prediction failed (${res.status})`)
      }
      const data = await res.json()
      setResponse(data)
      if (Array.isArray(data)) {
        setWarmupActive(data.some((row) => row.warmup))
      } else {
        setWarmupActive(Boolean(data?.warmup))
      }
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    if (!chartRef.current) return
    if (!chartInstanceRef.current) {
      chartInstanceRef.current = echarts.init(chartRef.current)
    }
    const chart = chartInstanceRef.current
    const times = response.map((item) => item.timestamp)
    const scores = response.map((item) =>
      item.warmup
        ? 0
        : item.calibrated_risk_score ?? item.risk_score
    )
    const rawScores = response.map((item) =>
      item.warmup
        ? 0
        : item.raw_margin ?? item.risk_score
    )
    const option = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          if (!params?.length) return ''
          const lines = params.map((p) => `${p.seriesName}: ${p.data}`)
          return `${params[0].axisValue}<br/>${lines.join('<br/>')}`
        },
      },
      grid: { left: 24, right: 24, top: 30, bottom: 40 },
      xAxis: {
        type: 'category',
        data: times,
        axisLabel: { color: '#8b98b3', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(126, 143, 170, 0.3)' } },
      },
      yAxis: [
        {
          type: 'value',
          min: 0,
          max: 1,
          axisLabel: { color: '#8b98b3', fontSize: 10 },
          splitLine: { lineStyle: { color: 'rgba(126, 143, 170, 0.2)' } },
        },
        {
          type: 'value',
          axisLabel: { color: '#8b98b3', fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'Calibrated Risk',
          type: 'line',
          data: scores,
          smooth: false,
          showSymbol: true,
          symbolSize: 6,
          lineStyle: { color: '#4f8cff', width: 2 },
          itemStyle: { color: '#4f8cff' },
          areaStyle: {
            color: 'rgba(79, 140, 255, 0.2)',
          },
        },
        {
          name: 'Raw Margin',
          type: 'line',
          data: rawScores,
          smooth: false,
          showSymbol: false,
          lineStyle: { color: '#ff6f6f', width: 1.5, type: 'dashed' },
          yAxisIndex: 1,
        },
      ],
    }
    chart.setOption(option)
    chart.off('click')
    chart.on('click', (params) => {
      if (params?.dataIndex !== undefined) {
        setSelectedIndex(params.dataIndex)
      }
    })
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [response])

  useEffect(() => {
    if (!payload?.length) return
    const keys = Object.keys(payload[0]?.features || {})
    setParamVisibility((prev) => {
      if (Object.keys(prev).length) return prev
      const next = {}
      keys.forEach((k) => {
        next[k] = true
      })
      return next
    })
  }, [payload])

  useEffect(() => {
    const charts = [
      chartInstanceRef.current,
      corrChartInstanceRef.current,
      matrixChartInstanceRef.current,
    ].filter(Boolean)
    charts.forEach((c) => c.resize())
  }, [activeTab])

  useEffect(() => {
    if (!corrChartRef.current) return
    if (!corrChartInstanceRef.current) {
      corrChartInstanceRef.current = echarts.init(corrChartRef.current)
    }
    const chart = corrChartInstanceRef.current
    if (!payload?.length || !response?.length) {
      chart.clear()
      return
    }

    const times = payload.map((item) => item.timestamp)
    const featureKeys = Object.keys(payload[0]?.features || {})
    const visibleKeys = featureKeys.filter((k) => paramVisibility[k])
    const series = visibleKeys.map((key) => ({
      name: key,
      type: 'line',
      data: payload.map((item) => item.features?.[key] ?? 0),
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 1 },
      emphasis: { focus: 'series' },
    }))

    series.push({
      name: 'Calibrated Risk',
      type: 'line',
      data: response.map((item) =>
        item.warmup ? 0 : item.calibrated_risk_score ?? item.risk_score
      ),
      smooth: false,
      showSymbol: false,
      lineStyle: { width: 3, color: '#4f8cff' },
      yAxisIndex: 1,
    })

    series.push({
      name: 'Raw Margin',
      type: 'line',
      data: response.map((item) =>
        item.warmup ? 0 : item.raw_margin ?? item.risk_score
      ),
      smooth: false,
      showSymbol: false,
      lineStyle: { width: 2, color: '#ff6f6f', type: 'dashed' },
      yAxisIndex: 2,
    })

    const option = {
      backgroundColor: 'transparent',
      legend: {
        type: 'scroll',
        top: 8,
        textStyle: { color: '#c6d0e0', fontSize: 10 },
      },
      tooltip: {
        trigger: 'axis',
      },
      grid: { left: 40, right: 50, top: 60, bottom: 40 },
      xAxis: {
        type: 'category',
        data: times,
        axisLabel: { color: '#8b98b3', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(126, 143, 170, 0.3)' } },
      },
      yAxis: [
        {
          type: 'value',
          axisLabel: { color: '#8b98b3', fontSize: 10 },
          splitLine: { lineStyle: { color: 'rgba(126, 143, 170, 0.15)' } },
        },
        {
          type: 'value',
          min: 0,
          max: 1,
          axisLabel: { color: '#8b98b3', fontSize: 10 },
          splitLine: { show: false },
        },
        {
          type: 'value',
          axisLabel: { color: '#8b98b3', fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series,
    }
    chart.setOption(option, true)
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [payload, response, paramVisibility])

  useEffect(() => {
    if (!matrixChartRef.current) return
    if (!matrixChartInstanceRef.current) {
      matrixChartInstanceRef.current = echarts.init(matrixChartRef.current)
    }
    const chart = matrixChartInstanceRef.current
    if (!payload?.length || !response?.length) {
      chart.clear()
      return
    }

    const featureKeys = Object.keys(payload[0]?.features || {})
    const visibleKeys = featureKeys.filter((k) => paramVisibility[k])
    const labels = [...visibleKeys, 'risk_score']

    const seriesData = payload.map((item, idx) => ({
      ...item.features,
      risk_score:
        response[idx]?.calibrated_risk_score ??
        response[idx]?.risk_score ??
        0,
    }))

    const matrix = []
    const getSeries = (key) => seriesData.map((r) => Number(r[key]) || 0)
    const corr = (a, b) => {
      const n = a.length
      const meanA = a.reduce((s, v) => s + v, 0) / n
      const meanB = b.reduce((s, v) => s + v, 0) / n
      let num = 0
      let denA = 0
      let denB = 0
      for (let i = 0; i < n; i += 1) {
        const da = a[i] - meanA
        const db = b[i] - meanB
        num += da * db
        denA += da * da
        denB += db * db
      }
      const denom = Math.sqrt(denA * denB) || 1
      return num / denom
    }

    for (let i = 0; i < labels.length; i += 1) {
      const a = getSeries(labels[i])
      for (let j = 0; j < labels.length; j += 1) {
        const b = getSeries(labels[j])
        matrix.push([i, j, Number(corr(a, b).toFixed(3))])
      }
    }

    const option = {
      backgroundColor: 'transparent',
      tooltip: {
        position: 'top',
        formatter: (p) => `${labels[p.data[1]]} vs ${labels[p.data[0]]}: ${p.data[2]}`,
      },
      grid: { left: 120, right: 40, top: 40, bottom: 80 },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: '#8b98b3', rotate: 45, fontSize: 10 },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: '#8b98b3', fontSize: 10 },
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 12,
        inRange: {
          color: ['#ff6f6f', '#f6f8fc', '#4f8cff'],
        },
        textStyle: { color: '#c6d0e0' },
      },
      series: [
        {
          name: 'Correlation',
          type: 'heatmap',
          data: matrix,
          label: { show: true, color: '#0b0f1a', fontSize: 9 },
          emphasis: {
            itemStyle: {
              shadowBlur: 6,
              shadowColor: 'rgba(0,0,0,0.3)',
            },
          },
        },
      ],
    }
    chart.setOption(option, true)
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [payload, response, paramVisibility])

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">PdM Prediction Service</p>
          <h1>Machine Risk Dashboard</h1>
        </div>
        <div className="status-pill">
          <span
            className={`status-dot ${token ? 'online' : 'offline'}`}
            aria-hidden="true"
          />
          <span>{tokenStatus}</span>
        </div>
      </header>
      {warmupActive ? (
        <div className="banner">
          Warmup in progress: at least 60 records (10 minutes) are required
          before predictions become valid.
        </div>
      ) : null}

      <div className="tabs">
        <button
          className={`tab ${activeTab === 'predict' ? 'active' : ''}`}
          onClick={() => setActiveTab('predict')}
        >
          Prediction
        </button>
        <button
          className={`tab ${activeTab === 'correlation' ? 'active' : ''}`}
          onClick={() => setActiveTab('correlation')}
        >
          Correlation View
        </button>
      </div>

      <main className="grid">
        {activeTab === 'predict' ? (
          <>
        <section className="card focus">
          <div className="card-head">
            <h2>Live Risk</h2>
            <span className="chip">{latest?.model_type || 'stub'}</span>
          </div>
          <div className="meter">
            <div className="meter-ring" style={{ '--value': riskPercent }}>
              <div className="meter-core">
                <p className="meter-value">{riskPercent}%</p>
                <p className="meter-label">
                  {latest?.risk_level || 'Awaiting data'}
                </p>
              </div>
            </div>
          </div>
          <div className="meta">
            <div>
              <span className="meta-label">Machine</span>
              <span className="meta-value">
                {latest?.machine_id || machineId}
              </span>
            </div>
            <div>
              <span className="meta-label">Timestamp</span>
              <span className="meta-value">
                {latest?.timestamp || timestamp || '—'}
              </span>
            </div>
          </div>
        </section>

        <section className="card form">
          <div className="card-head">
            <h2>API Connection</h2>
            <span className="chip quiet">OAuth2</span>
          </div>
          <div className="field">
            <label htmlFor="baseUrl">Base URL</label>
            <input
              id="baseUrl"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="username">Username</label>
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
          <button className="primary" onClick={requestToken}>
            Get Token
          </button>
        </section>

        <section className="card form">
          <div className="card-head">
            <h2>Prediction Request</h2>
            <span className="chip">{token ? 'Authorized' : 'No token'}</span>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="machineId">Machine ID</label>
              <input
                id="machineId"
                value={machineId}
                onChange={(e) => setMachineId(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="timestamp">Timestamp</label>
              <input
                id="timestamp"
                value={timestamp}
                onChange={(e) => setTimestamp(e.target.value)}
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="features">Batch Payload (JSON Array)</label>
            <textarea
              id="features"
              rows="12"
              value={featuresJson}
              onChange={(e) => setFeaturesJson(e.target.value)}
            />
          </div>
          <button className="primary" onClick={sendPrediction}>
            Send Prediction
          </button>
          {error ? <p className="error">{error}</p> : null}
        </section>

        <section className="card detail">
          <div className="card-head">
            <h2>Selected Input + Response</h2>
            <span className="chip quiet">
              {latestIndex !== null ? `Index ${latestIndex + 1}` : '—'}
            </span>
          </div>
          <div className="split">
            <div>
              <p className="split-label">Input JSON</p>
              <pre>
                {payload?.length && latestIndex !== null
                  ? JSON.stringify(payload[latestIndex], null, 2)
                  : '—'}
              </pre>
            </div>
            <div>
              <p className="split-label">Response JSON</p>
              <pre>
                {response?.length && latestIndex !== null
                  ? JSON.stringify(response[latestIndex], null, 2)
                  : '—'}
              </pre>
            </div>
          </div>
        </section>

        <section className="card detail">
          <div className="card-head">
            <h2>Risk Score Trend</h2>
            <span className="chip quiet">ECharts</span>
          </div>
          <div className="chart" ref={chartRef} />
        </section>
          </>
        ) : (
          <section className="card detail full">
            <div className="card-head">
              <h2>Parameter Correlation</h2>
              <span className="chip quiet">All Params + Risk</span>
            </div>
            <div className="toggle-row">
              {Object.keys(paramVisibility).length ? (
                Object.keys(paramVisibility).map((key) => (
                  <label className="toggle" key={key}>
                    <input
                      type="checkbox"
                      checked={paramVisibility[key]}
                      onChange={(e) =>
                        setParamVisibility((prev) => ({
                          ...prev,
                          [key]: e.target.checked,
                        }))
                      }
                    />
                    <span>{key}</span>
                  </label>
                ))
              ) : (
                <span className="hint">Send a batch prediction first.</span>
              )}
            </div>
            <div className="chart big" ref={corrChartRef} />
            <div className="chart matrix" ref={matrixChartRef} />
            {!payload?.length || !response?.length ? (
              <p className="hint">Send a batch prediction to populate this view.</p>
            ) : null}
          </section>
        )}
      </main>
    </div>
  )
}

export default App
