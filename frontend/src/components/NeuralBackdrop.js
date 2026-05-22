// Phase 12.15.12: Neural network 背景動畫 — Dashboard 路由可見
//
// Canvas 實現極輕量神經網絡：
// - 30 節點隨機分佈 + 重力漂移
// - 距離 < threshold 自動連線
// - 隨機脈衝沿連線流動（每 2-5s 一個）
// - 紫色 (AI accent) + cyan (system accent) 混合
//
// 性能：fixed z-index -1, position: fixed, opacity 0.3, 不 block 主內容點擊
// CPU：30 nodes × 60fps ~3% (single thread)

import React, { useEffect, useRef } from 'react';
import { palette } from '../theme';

const NODE_COUNT = 28;
const LINK_DISTANCE = 180;       // 节点距离 < 此值才连线
const NODE_SPEED = 0.18;         // 漂移速度（每帧 px）
const PULSE_INTERVAL_MS = 2500;  // 平均多少 ms 触发一个脉冲

function rand(min, max) {
  return min + Math.random() * (max - min);
}

export default function NeuralBackdrop({ enabled = true }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let nodes = [];
    let pulses = [];   // 沿连线流动的脉冲粒子
    let lastPulseTime = 0;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      ctx.scale(dpr, dpr);
    };

    const init = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      nodes = Array.from({ length: NODE_COUNT }, () => ({
        x: rand(0, w),
        y: rand(0, h),
        vx: rand(-NODE_SPEED, NODE_SPEED),
        vy: rand(-NODE_SPEED, NODE_SPEED),
        r: rand(1.5, 3),
        isAi: Math.random() < 0.35,   // 35% AI 紫色，65% system cyan
      }));
    };

    const findLinks = () => {
      const links = [];
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < LINK_DISTANCE) {
            links.push({ i, j, dist, alpha: (1 - dist / LINK_DISTANCE) * 0.5 });
          }
        }
      }
      return links;
    };

    const triggerPulse = (links) => {
      if (links.length === 0) return;
      const link = links[Math.floor(Math.random() * links.length)];
      pulses.push({
        i: link.i, j: link.j, t: 0,
        color: nodes[link.i].isAi || nodes[link.j].isAi ? palette.ai : palette.accent,
      });
    };

    const draw = (timestamp) => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.clearRect(0, 0, w, h);

      // Move nodes
      for (const n of nodes) {
        n.x += n.vx; n.y += n.vy;
        // bounce off edges
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
      }

      // Compute links
      const links = findLinks();

      // Draw links
      for (const link of links) {
        const a = nodes[link.i];
        const b = nodes[link.j];
        const isAiLink = a.isAi || b.isAi;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = isAiLink
          ? `rgba(167, 139, 250, ${link.alpha * 0.35})`
          : `rgba(6, 182, 212, ${link.alpha * 0.35})`;
        ctx.lineWidth = 0.6;
        ctx.stroke();
      }

      // Draw nodes
      for (const n of nodes) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = n.isAi ? palette.ai : palette.accent;
        ctx.globalAlpha = 0.55;
        ctx.fill();
        // glow
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * 2.5, 0, Math.PI * 2);
        ctx.fillStyle = n.isAi
          ? `rgba(167, 139, 250, 0.12)`
          : `rgba(6, 182, 212, 0.12)`;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Trigger new pulse periodically
      if (timestamp - lastPulseTime > PULSE_INTERVAL_MS + rand(-800, 800)) {
        triggerPulse(links);
        lastPulseTime = timestamp;
      }

      // Draw + advance pulses
      pulses = pulses.filter(p => p.t < 1);
      for (const p of pulses) {
        const a = nodes[p.i];
        const b = nodes[p.j];
        if (!a || !b) continue;
        const x = a.x + (b.x - a.x) * p.t;
        const y = a.y + (b.y - a.y) * p.t;
        // glowing dot
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 10;
        ctx.fill();
        ctx.shadowBlur = 0;
        p.t += 0.012;
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    resize();
    init();
    rafRef.current = requestAnimationFrame(draw);
    window.addEventListener('resize', () => { resize(); init(); });

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', resize);
    };
  }, [enabled]);

  if (!enabled) return null;

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0, left: 0, width: '100vw', height: '100vh',
        pointerEvents: 'none',
        zIndex: 0,
        opacity: 0.55,
      }}
    />
  );
}
