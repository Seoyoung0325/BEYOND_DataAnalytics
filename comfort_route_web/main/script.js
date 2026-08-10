const sidebar = document.getElementById("sidebar");
const toggleBtn = document.getElementById("toggle-btn");

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");

  if (sidebar.classList.contains("collapsed")) {
    toggleBtn.textContent = "›››";
  } else {
    toggleBtn.textContent = "‹‹‹";
  }
});