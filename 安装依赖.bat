python -m venv venv
start cmd /k "venv\Scripts\activate && python -m pip install -r requirements.txt && pause && exit"
git rm --cached 安装依赖.bat
git add start.bat
git commit -m "修复 start.bat 乱码问题"
