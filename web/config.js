// ランキングの保存先（Supabase）。空のままならランキング機能は表示されない。
// 設定方法は web/README.md を参照。publishable key（旧 anon key）は公開してよい鍵で、
// できることは web/supabase.sql の権限設定（読む・追加する）に限られる。
window.FEVER_CONFIG = {
  supabaseUrl: "",
  supabaseKey: "",
};
