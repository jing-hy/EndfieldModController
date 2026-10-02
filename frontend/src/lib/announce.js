// 公告条数据适配：后端 state.announcements 是一个列表，字段名以 alerts 模块为准，
// 这里做容错（title/message/body、level/kind 都可能叫法不同），避免一处改名就整条不显示。
export function normalizeAnnouncements(list) {
  return (Array.isArray(list) ? list : [])
    .map((a, i) => ({
      key: String(a.id || a.key || i),
      title: String(a.title || a.name || ""),
      body: String(a.body || a.message || a.text || ""),
      level: String(a.level || a.kind || "info"),
      link: a.link || a.url || "",
    }))
    .filter((a) => a.title || a.body);
}
