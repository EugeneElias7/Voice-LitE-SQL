import { useEffect, useRef, useState } from 'react'

interface DataViz3DProps {
  state: 'idle' | 'listening' | 'transcribing' | 'understanding' | 'retrieval' | 'generation' | 'validation' | 'execution' | 'answer' | 'error'
  className?: string
}

const NODE_COUNT = 80

interface Node {
  x: number
  y: number
  z: number
  baseX: number
  baseY: number
  baseZ: number
  vx: number
  vy: number
  vz: number
  color: string
  size: number
  type: 'data' | 'schema' | 'query' | 'result' | 'connector'
  connections: number[]
}

const COLORS = {
  data: '#00d4aa',
  schema: '#6f8dff',
  query: '#b39af6',
  result: '#ffc877',
  connector: '#4a5a7a',
}

function generateNodes(): Node[] {
  const nodes: Node[] = []
  const types: Node['type'][] = ['data', 'schema', 'query', 'result']

  for (let i = 0; i < NODE_COUNT; i++) {
    const radius = 12 * (0.3 + Math.random() * 0.7)
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    const x = radius * Math.sin(phi) * Math.cos(theta)
    const y = radius * Math.sin(phi) * Math.sin(theta)
    const z = radius * Math.cos(phi)
    const type = types[Math.floor(Math.random() * types.length)]

    nodes.push({
      x, y, z,
      baseX: x, baseY: y, baseZ: z,
      vx: 0, vy: 0, vz: 0,
      color: COLORS[type],
      size: 1.5 + Math.random() * 2.5,
      type,
      connections: [],
    })
  }

  // Build connections
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[i].x - nodes[j].x
      const dy = nodes[i].y - nodes[j].y
      const dz = nodes[i].z - nodes[j].z
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (dist < 2.8 && Math.random() > 0.6) {
        nodes[i].connections.push(j)
        nodes[j].connections.push(i)
      }
    }
  }

  return nodes
}

function project3D(node: Node, cameraZ: number, width: number, height: number): { x: number; y: number; scale: number } {
  const fov = 45 * Math.PI / 180
  const f = 1 / Math.tan(fov / 2)
  const z = cameraZ - node.z

  if (z <= 0.1) return { x: width / 2, y: height / 2, scale: 0 }

  const scale = f / z
  return {
    x: width / 2 + node.x * scale * width / 2,
    y: height / 2 - node.y * scale * width / 2,
    scale,
  }
}

export function DataViz3D({ state, className }: DataViz3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [nodes] = useState(() => generateNodes())
  const [audioAmplitude, setAudioAmplitude] = useState(0)
  const timeRef = useRef(0)
  const animationRef = useRef<number | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      canvas.width = canvas.offsetWidth * dpr
      canvas.height = canvas.offsetHeight * dpr
      canvas.style.width = canvas.offsetWidth + 'px'
      canvas.style.height = canvas.offsetHeight + 'px'
      ctx.scale(dpr, dpr)
    }

    resize()
    window.addEventListener('resize', resize)

    const animate = () => {
      timeRef.current += 1 / 60

      const width = canvas.offsetWidth
      const height = canvas.offsetHeight
      const cameraZ = 22
      const amp = audioAmplitude

      // Clear
      ctx.clearRect(0, 0, width, height)

      // Update nodes
      nodes.forEach((node, i) => {
        const t = timeRef.current
        const floatFreq = 0.5 + (i % 7) * 0.15
        const floatAmp = 0.15 + (node.type === 'connector' ? 0.1 : 0)

        node.x = node.baseX + Math.sin(t * floatFreq + i) * floatAmp
        node.y = node.baseY + Math.cos(t * floatFreq * 1.3 + i * 2) * floatAmp
        node.z = node.baseZ + Math.sin(t * floatFreq * 0.7 + i * 3) * floatAmp

        // State-specific behaviors
        switch (state) {
          case 'listening': {
            const distToCenter = Math.sqrt(node.x * node.x + node.y * node.y + node.z * node.z)
            const pulseWave = Math.sin(t * 8 - distToCenter * 1.5) * 0.3 * amp
            if (distToCenter > 0.01) {
              node.x += (node.x / distToCenter) * pulseWave
              node.y += (node.y / distToCenter) * pulseWave
              node.z += (node.z / distToCenter) * pulseWave
            }
            break
          }
          case 'transcribing': {
            const distToCenter = Math.sqrt(node.x * node.x + node.y * node.y + node.z * node.z)
            if (distToCenter > 0.01) {
              node.x -= (node.x / distToCenter) * (1 / 60) * 1.5 * (1 + amp * 2)
              node.y -= (node.y / distToCenter) * (1 / 60) * 1.5 * (1 + amp * 2)
              node.z -= (node.z / distToCenter) * (1 / 60) * 1.5 * (1 + amp * 2)
            }
            break
          }
          case 'understanding': {
            node.x += (node.baseX - node.x) * (1 / 60) * 2
            node.y += (node.baseY - node.y) * (1 / 60) * 2
            node.z += (node.baseZ - node.z) * (1 / 60) * 2
            break
          }
          case 'retrieval': {
            if (node.type === 'schema') {
              const pulse = Math.sin(t * 6 + i) * 0.5 + 0.5
              node.y += Math.sin(t * 4 + i) * 0.1 * pulse
            }
            break
          }
          case 'generation': {
            if (node.type === 'query') {
              node.x += (Math.random() - 0.5) * 0.15
              node.y += (Math.random() - 0.5) * 0.15
              node.z += (Math.random() - 0.5) * 0.15
            }
            break
          }
          case 'validation': {
            node.x += (node.baseX - node.x) * (1 / 60) * 1.5
            node.y += (node.baseY - node.y) * (1 / 60) * 1.5
            node.z += (node.baseZ - node.z) * (1 / 60) * 1.5
            break
          }
          case 'execution': {
            if (node.type === 'schema') {
              node.x += (3 - node.x) * (1 / 60) * 0.8
            } else if (node.type === 'result') {
              node.x += Math.sin(t * 5 + i) * 0.05
            }
            break
          }
          case 'answer': {
            node.x += (node.baseX - node.x) * (1 / 60) * 1.2
            node.y += (node.baseY - node.y) * (1 / 60) * 1.2
            node.z += (node.baseZ - node.z) * (1 / 60) * 1.2
            break
          }
          case 'error': {
            if (node.type !== 'connector') {
              const pulse = Math.sin(t * 4) * 0.5 + 0.5
              node.y += Math.sin(t * 3 + i) * 0.08 * pulse
            }
            break
          }
        }

        // Audio reactivity
        if (amp > 0.1) {
          const audioPush = amp * 0.5
          node.x += (Math.random() - 0.5) * audioPush
          node.y += (Math.random() - 0.5) * audioPush
          node.z += (Math.random() - 0.5) * audioPush
        }
      })

      // Draw connections first
      ctx.strokeStyle = 'rgba(74, 90, 122, 0.15)'
      ctx.lineWidth = 0.5

      nodes.forEach((node, i) => {
        const pos1 = project3D(node, cameraZ, width, height)
        if (pos1.scale <= 0) return

        node.connections.forEach(connIdx => {
          if (connIdx > i) {
            const target = nodes[connIdx]
            const pos2 = project3D(target, cameraZ, width, height)
            if (pos2.scale <= 0) return

            const dist3D = Math.sqrt(
              Math.pow(node.x - target.x, 2) +
              Math.pow(node.y - target.y, 2) +
              Math.pow(node.z - target.z, 2)
            )

            let opacity = 0
            if (dist3D < 2.8 * 1.2) {
              switch (state) {
                case 'understanding':
                case 'retrieval':
                  opacity = 0.3
                  break
                case 'generation':
                  opacity = 0.4
                  break
                case 'execution':
                  opacity = 0.5
                  break
                case 'answer':
                  opacity = 0.2
                  break
                default:
                  opacity = 0.1
              }
            }

            if (opacity > 0.05) {
              ctx.globalAlpha = opacity
              ctx.beginPath()
              ctx.moveTo(pos1.x, pos1.y)
              ctx.lineTo(pos2.x, pos2.y)
              ctx.stroke()
            }
          }
        })
      })

      ctx.globalAlpha = 1

      // Draw nodes
      nodes.forEach((node, _i) => {
        const pos = project3D(node, cameraZ, width, height)
        if (pos.scale <= 0) return

        const size = Math.max(1, node.size * pos.scale * 2)

        // Node glow
        const gradient = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, size * 3)
        gradient.addColorStop(0, node.color)
        gradient.addColorStop(1, 'transparent')

        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, size * 3, 0, Math.PI * 2)
        ctx.fill()

        // Node core
        ctx.fillStyle = node.color
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, size, 0, Math.PI * 2)
        ctx.fill()
      })

      // Central processing indicator
      if (['transcribing', 'understanding', 'generation', 'validation'].includes(state)) {
        const centerX = width / 2
        const centerY = height / 2
        const pulseScale = 0.5 + 0.5 * Math.sin(timeRef.current * 4)
        const radius = 30 * pulseScale

        const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius)
        gradient.addColorStop(0, 'rgba(111, 141, 255, 0.4)')
        gradient.addColorStop(1, 'rgba(111, 141, 255, 0)')

        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2)
        ctx.fill()
      }

      // Listening ring
      if (state === 'listening') {
        const centerX = width / 2
        const centerY = height / 2
        const ringScale = (Math.sin(timeRef.current * 3) * 0.5 + 0.5) * 1.5 + 0.5
        const radius = 60 * ringScale
        const opacity = 0.6 * (1 - (ringScale - 0.5) / 1.5)

        ctx.strokeStyle = `rgba(255, 122, 122, ${opacity})`
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2)
        ctx.stroke()
      }

      animationRef.current = requestAnimationFrame(animate)
    }

    animationRef.current = requestAnimationFrame(animate)

    return () => {
      window.removeEventListener('resize', resize)
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [state, audioAmplitude])

  // Expose audio amplitude setter globally for voice input
  useEffect(() => {
    ;(window as any).__setAudioAmplitude = (amp: number) => {
      setAudioAmplitude(Math.max(0, Math.min(1, amp)))
    }
  }, [])

  return <canvas ref={canvasRef} className={className} style={{ position: 'absolute', inset: 0, zIndex: 0 }} />
}