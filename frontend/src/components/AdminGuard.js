// Phase 14j: admin-only 路由守护
// 非 admin user 访问 /admin/* → 跳转 /dashboard
// (后端 @require_admin 是真正的安全防线, 前端只是 UX 引导)

import React, { useState, useEffect } from 'react';
import { Navigate } from 'react-router-dom';
import { getUser, onUserChange } from '../auth';

export default function AdminGuard({ children }) {
  const [user, setUser] = useState(getUser());

  useEffect(() => onUserChange(setUser), []);

  if (!user || user.role !== 'admin') {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}
