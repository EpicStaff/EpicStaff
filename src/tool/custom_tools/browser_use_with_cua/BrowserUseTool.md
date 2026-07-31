How to set up a project:
1. change directory:
```bash 
cd C:\Projects\EpicStaff\src\tool\custom_tools\browser_use_with_cua
```
2. build docker container:
```bash 
docker compose build
```
3. run container:
```bash 
docker compose up -d
```
4. if you want to see logs:
```bash 
docker compose logs -f
```
5. open new terminal and go to same directory:
```bash 
cd C:\Projects\EpicStaff\src\tool\custom_tools\browser_use_with_cua
```
6. run test client:
```bash
python test_client.py
```
To see the flow running in headfull mode download realVNC and use localhost:5900 with pass: "secret"