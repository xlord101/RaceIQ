'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, useScroll, useTransform } from 'framer-motion'

const sections = [
  ['01', 'Problem'],
  ['02', 'Energy'],
  ['03', 'Overtake'],
  ['04', 'Risk / reward'],
  ['05', 'Compliance'],
  ['06', 'Decision'],
  ['07', 'Product'],
  ['08', 'Architecture'],
]

const concepts = [
  ['01', 'ENERGY', 'Electrical energy is finite. Deploying now changes what remains later.'],
  ['02', 'OVERTAKE', 'A passing opportunity is actionable only when the opponent and race state support it.'],
  ['03', 'RISK / REWARD', 'A successful pass can gain position while increasing energy use and exposure to repass.'],
  ['04', 'RULE COMPLIANCE', 'The best strategy must remain legal under the governing race rules.'],
]

function Reveal({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <motion.div className={className} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .2 }} transition={{ duration: .7, ease: 'easeOut' }}>{children}</motion.div>
}

function Section({ id, number, label, title, children }: { id: string; number: string; label: string; title: React.ReactNode; children: React.ReactNode }) {
  return <section id={id} className="story-section"><div className="section-rail"><span>{number}</span><i /></div><Reveal className="section-body"><p className="eyebrow">{label}</p><h2>{title}</h2>{children}</Reveal></section>
}

function Flow({ items }: { items: string[] }) {
  return <div className="flow">{items.map((item, i) => <div className="flow-item" key={item}><span>{item}</span>{i < items.length - 1 && <b>↓</b>}</div>)}</div>
}

function CarTrack() {
  const pathRef = useRef<SVGPathElement>(null)
  const carRef = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll()
  const line = useTransform(scrollYProgress, [0, 1], ['0%', '100%'])

  useEffect(() => {
    let frame = 0
    const update = () => {
      const path = pathRef.current
      const car = carRef.current
      if (!path || !car) return
      const length = path.getTotalLength()
      const progress = Math.max(0, Math.min(1, window.scrollY / Math.max(1, document.documentElement.scrollHeight - window.innerHeight)))
      const distance = progress * length
      const point = path.getPointAtLength(distance)
      const before = path.getPointAtLength(Math.max(0, distance - 2))
      const after = path.getPointAtLength(Math.min(length, distance + 2))
      const angle = Math.atan2(after.y - before.y, after.x - before.x) * 180 / Math.PI
      car.style.left = `${point.x / 10}%`
      car.style.top = `${point.y / 10}%`
      car.style.transform = `translate(-50%, -50%) rotate(${angle}deg)`
      frame = 0
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update) }
    update()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => { cancelAnimationFrame(frame); window.removeEventListener('scroll', schedule); window.removeEventListener('resize', schedule) }
  }, [])

  return <div className="track-layer" aria-hidden="true">
    <svg className="track-svg" viewBox="0 0 1000 1000" preserveAspectRatio="none">
      <path ref={pathRef} className="track-path-faint" d="M850 130 C570 145 245 145 210 235 S675 320 790 410 S730 520 325 605 S220 760 735 850" />
      <path className="track-path" d="M850 130 C570 145 245 145 210 235 S675 320 790 410 S730 520 325 605 S220 760 735 850" pathLength="1" />
      <motion.path className="track-progress" d="M850 130 C570 145 245 145 210 235 S675 320 790 410 S730 520 325 605 S220 760 735 850" pathLength="1" style={{ pathLength: line }} />
    </svg>
    <div ref={carRef} className="track-car"><img src="https://hebbkx1anhila5yf.public.blob.vercel-storage.com/image-removebg-preview-XHKUc3z8NCMg9Mo1DGqkIIuEnpyAGX.png" alt="" /></div>
  </div>
}

export default function Page() {
  const [active, setActive] = useState('01')
  useEffect(() => {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => entry.isIntersecting && setActive(entry.target.id.slice(1))), { rootMargin: '-35% 0px -55% 0px' })
    sections.forEach(([number]) => { const element = document.getElementById(`s${number}`); if (element) observer.observe(element) })
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return

      const forward = ['ArrowDown', 'ArrowRight', 'PageDown', ' '].includes(event.key)
      const backward = ['ArrowUp', 'ArrowLeft', 'PageUp'].includes(event.key)
      if (!forward && !backward) return

      const destinations = ['hero', ...sections.map(([number]) => `s${number}`)]
        .map(id => document.getElementById(id))
        .filter((element): element is HTMLElement => Boolean(element))
      const current = window.scrollY
      const nextIndex = forward
        ? (() => {
          const next = destinations.findIndex(element => element.offsetTop > current + 100)
          return next === -1 ? destinations.length - 1 : next
        })()
        : Math.max(0, destinations.reduce((last, element, index) => element.offsetTop < current - 100 ? index : last, 0))

      event.preventDefault()
      destinations[nextIndex]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return <main className="raceiq-page">
    <CarTrack />
    <header className="topbar"><a href="#hero" className="brand">RACE<span>IQ</span></a><span className="topbar-label">ENERGY &amp; OVERTAKE INTELLIGENCE <i /> SYSTEM OVERVIEW</span></header>
    <nav className="side-nav" aria-label="Presentation sections">{sections.map(([number, name]) => <a key={number} href={`#s${number}`} className={active === number ? 'active' : ''}><span>{number}</span><em>{name}</em></a>)}</nav>

    <section id="hero" className="hero"><div className="hero-grid" /><div className="hero-copy"><p className="eyebrow">ENERGY &amp; OVERTAKE INTELLIGENCE</p><h1>How should a race car spend its <span>finite electrical energy?</span></h1><p className="hero-statement">Optimizing finite electrical energy deployment while balancing immediate overtake opportunities against long-term race performance and rule compliance.</p><div className="concept-strip">{['ENERGY', 'OVERTAKE', 'RISK / REWARD', 'RULE COMPLIANCE'].map(x => <span key={x}>{x}</span>)}</div><p className="hero-answer">RaceIQ turns these competing demands into a decision.</p><div className="scroll-cue">SCROLL TO FOLLOW THE DECISION <b>↓</b></div></div></section>

    <Section id="s01" number="01" label="THE PROBLEM" title={<>Four constraints.<br /><span>One race.</span></>}><div className="concept-list">{concepts.map(([number, name, copy]) => <motion.div key={name} className="concept-row" whileInView={{ opacity: 1, x: 0 }} initial={{ opacity: 0, x: -18 }} viewport={{ once: true }}><small>{number}</small><strong>{name}</strong><p>{copy}</p></motion.div>)}</div></Section>

    <Section id="s02" number="02" label="THE APPROACH" title={<>Four questions.<br /><span>One decision engine.</span></>}><div className="converge"><div>{['ENERGY', 'OVERTAKE', 'RISK / REWARD', 'RULE COMPLIANCE'].map(x => <span key={x}>{x}</span>)}</div><b>→</b><strong>RACE<span>IQ</span></strong></div><Flow items={['RACE STATE', 'ENERGY STATE', 'OPPONENT STATE', 'PASS PROBABILITY', 'STRATEGIC VALUE', 'DECISION']} /></Section>

    <Section id="s03" number="03" label="1 — ENERGY" title={<>Estimate what the car<br /><span>can spend.</span></>}><p className="section-lede">Estimate where the car&apos;s electrical energy stands before deciding where to spend it.</p><div className="energy-layout"><Flow items={['RACE TELEMETRY + TRACK CONTEXT + ENERGY RULES', 'SoC OBSERVER', 'ESTIMATED ENERGY STATE']} /><div className="energy-panel"><Label>INFERRED</Label><svg viewBox="0 0 600 150" className="trace"><path d="M0 108 C80 90 90 120 150 72 S230 120 290 74 S370 45 430 82 S520 42 600 52" /></svg><div className="energy-values"><span>SoC TREND</span><strong>ERS STATE</strong><span>HARVEST / DEPLOY</span></div></div></div><p className="callout">RaceIQ estimates energy state from observable race information and domain constraints.</p></Section>

    <Section id="s04" number="04" label="2 — OVERTAKE" title={<>An opportunity is useful<br /><span>only if it is actionable.</span></>}><p className="section-lede">The opponent and race state determine whether a passing window is worth using.</p><div className="overtake-flow"><div><Label>OUR DRIVER</Label><strong>OCO</strong></div><b>↓</b><div><Label>CAR AHEAD</Label><strong>GAS — P9</strong></div><Flow items={['RACE STATE + TRACK + TYRES + ENERGY + OPPONENT STATE', 'PASS MODEL', 'P(PASS)']} /></div><div className="pass-result"><Label>ILLUSTRATIVE / CALCULATED</Label><strong>68<span>%</span></strong><small>PASS PROBABILITY</small></div></Section>

    <Section id="s05" number="05" label="3 — RISK / REWARD" title={<>Passing is not automatically<br /><span>the optimal decision.</span></>}><p className="section-lede">RaceIQ evaluates the value of acting now against what that action costs later.</p><div className="equation"><span>P(PASS)</span><b>×</b><span>VALUE OF POSITION</span><b>−</b><span>ENERGY COST</span><b>−</b><span>REPASS RISK</span><b>−</b><span>FUTURE OPPORTUNITY COST</span><b>−</b><span>COMPLIANCE RISK</span><b>↓</b><strong>STRATEGIC VALUE</strong></div><div className="choice-row"><span>ATTACK</span><i>or</i><span>HOLD</span></div></Section>

    <Section id="s06" number="06" label="4 — RULE COMPLIANCE" title={<>Speed is useful only when<br /><span>the strategy remains legal.</span></>}><p className="section-lede">Compliance is part of the decision, not a check performed afterward.</p><div className="compliance-flow"><Flow items={['2026 FIA RULES', 'CONSTRAINTS', 'DECISION']} /><Label>RULE COMPLIANCE</Label></div></Section>

    <Section id="s07" number="07" label="THE DECISION" title={<>All four become<br /><span>one decision.</span></>}><div className="decision-flow"><Flow items={['ENERGY', 'OVERTAKE', 'RISK / REWARD', 'RULE COMPLIANCE', 'RACEIQ', 'DECISION']} /></div><div className="decision-example"><Label tone="red">ILLUSTRATIVE</Label><small>HAAS — OCO</small><strong>ATTACK</strong><p>CAR AHEAD → PASS OPPORTUNITY → ENERGY STATE → RISK / REWARD → RACEIQ</p></div><div className="actions">{['ATTACK', 'HOLD', 'DEFEND', 'HARVEST'].map(x => <span key={x}>{x}</span>)}</div></Section>

    <Section id="s08" number="08" label="FROM DECISION TO PRODUCT" title={<>One engine.<br /><span>Four views.</span></>}><div className="product-views">{[['LIVE RACE', 'What is happening?'], ['WHAT IF', 'What changes if we act differently?'], ['WHY', 'Why did RaceIQ recommend this?'], ['IMPACT', 'What does this change for race engineering?']].map(([name, copy]) => <div key={name}><strong>{name}</strong><span>{copy}</span></div>)}</div><div className="architecture"><Flow items={['ACTUAL RACE DATA', 'ENERGY INFERENCE', 'OPPONENT INFERENCE', 'PASS PROBABILITY', 'STRATEGIC VALUE', 'RULE CONSTRAINTS', 'RACEIQ DECISION', 'ENGINEER INTERFACE']} /><p>ACTUAL → INFERRED → CALCULATED → PROJECTED</p></div><p className="callout">RaceIQ separates what happened from what the model infers and what it projects.</p></Section>

    <footer className="closing"><p className="eyebrow">BUILT FOR RACE ENGINEERING</p><h2>RACE<span>IQ</span></h2><p className="closing-label">ENERGY &amp; OVERTAKE INTELLIGENCE</p><h3>Spend energy where it matters.<br />Attack when the opportunity is worth it.<br />Protect the race that remains.</h3></footer>
  </main>
}

function Label({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'red' }) {
  return <span className={`label ${tone}`}>{children}</span>
}
