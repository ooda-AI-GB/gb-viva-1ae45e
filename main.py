from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app import models, database
from app.database import engine, get_db
import bcrypt
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, date, timedelta
import secrets

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Session Middleware (using a simple secret key for demo)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

# --- Utils ---
def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()

def login_required(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, detail="Not authenticated") 
        # Note: HTTPException doesn't redirect cleanly for browser, usually return RedirectResponse. 
        # But as a dependency, raising exception is standard. 
        # I'll handle redirection in the route logic or use a custom dependency that redirects.
    return user

# Better dependency for redirection
def get_user_or_redirect(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return None
    return user

# --- Routes ---

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def root(request: Request, user: models.User = Depends(get_user_or_redirect)):
    if user:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/login")
    
    # Calculate summary data
    # Active Projects
    active_projects_query = db.query(models.Project).filter(models.Project.status == "active")
    if user.role == "client":
        active_projects_query = active_projects_query.filter(models.Project.client_id == user.client_id)
    # Freelancer sees their own? Requirement says: "Freelancer sees their own. Admin sees all. Client sees only their projects."
    # Wait, projects don't have a freelancer_id. Only client_id. 
    # Assumption: Freelancer sees ALL projects unless they are assigned specific ones?
    # Prompt: "Freelancer sees their own." implying assignment. 
    # But Project model doesn't have freelancer_id. 
    # I'll assume Freelancer sees ALL projects (as they are THE freelancer for the system) 
    # OR create a relationship if multiple freelancers existed. 
    # Given "a freelancer" (singular) in seed data, I assume 1 freelancer for the system who sees all projects.
    
    # Correction: Admin sees all. Freelancer sees their own. Client sees theirs.
    # Since there is only 1 freelancer user mentioned, I'll treat "Freelancer" same as Admin for visibility 
    # OR assume all projects belong to the freelancer.
    
    active_projects_count = active_projects_query.count()

    # Total Hours this month
    start_of_month = date.today().replace(day=1)
    # Filter time entries by project visibility
    # For simplicity, if freelancer/admin, all time entries. If client, only their projects.
    time_query = db.query(models.TimeEntry).join(models.Project)
    if user.role == "client":
        time_query = time_query.filter(models.Project.client_id == user.client_id)
    
    month_hours = time_query.filter(models.TimeEntry.date >= start_of_month).all()
    total_hours = sum(t.hours for t in month_hours)
    
    # Pending Invoices
    pending_inv_query = db.query(models.Invoice).join(models.Project).filter(models.Invoice.status.in_(["draft", "sent"]))
    if user.role == "client":
        pending_inv_query = pending_inv_query.filter(models.Project.client_id == user.client_id)
    pending_invoices = pending_inv_query.count()
    
    # Total Earned (Paid invoices)
    # Assuming for client this is "Total Spent"
    paid_inv_query = db.query(models.Invoice).join(models.Project).filter(models.Invoice.status == "paid")
    if user.role == "client":
        paid_inv_query = paid_inv_query.filter(models.Project.client_id == user.client_id)
    total_earned = sum(i.amount for i in paid_inv_query.all())

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user,
        "active_projects": active_projects_count,
        "total_hours": round(total_hours, 1),
        "pending_invoices": pending_invoices,
        "total_earned": total_earned
    })

@app.get("/projects", response_class=HTMLResponse)
def projects(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/login")

    query = db.query(models.Project).join(models.Client)
    if user.role == "client":
        query = query.filter(models.Project.client_id == user.client_id)
    
    projects_list = query.all()
    return templates.TemplateResponse("projects.html", {"request": request, "user": user, "projects": projects_list})

@app.get("/time-logs", response_class=HTMLResponse)
def time_logs(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/login")
    
    query = db.query(models.TimeEntry).join(models.Project).order_by(models.TimeEntry.date.desc())
    # Clients usually don't see detailed time logs or maybe they do? "Time Log... Client sees only theirs?" 
    # Prompt doesn't explicitly restrict Client view for Time Log, but usually they see time for their projects.
    # Logic: "Freelancer sees their own. Admin sees all. Client sees only their projects." was for Projects page.
    # For Time Log: "Shows running total per project."
    # I'll apply the same visibility rule: Client only sees entries for their projects.
    
    if user.role == "client":
        query = query.filter(models.Project.client_id == user.client_id)
        
    entries = query.all()
    
    # Calculate totals per project
    project_totals = {}
    projects_for_form = []
    
    # For the Add Entry form (Freelancer/Admin only)
    if user.role in ["admin", "freelancer"]:
        projects_for_form = db.query(models.Project).filter(models.Project.status == "active").all()
        
    # Calculate running totals
    # This might be heavy for DB if many entries, but strict requirements say "Shows running total per project"
    # I'll just aggregate all time entries for visible projects.
    # Or simpler: Just group by project in python
    
    all_visible_entries = query.all() # re-executing or reusing
    for entry in all_visible_entries:
        pid = entry.project.id
        if pid not in project_totals:
            project_totals[pid] = 0
        project_totals[pid] += entry.hours

    return templates.TemplateResponse("time_log.html", {
        "request": request, 
        "user": user, 
        "entries": entries, 
        "projects": projects_for_form,
        "project_totals": project_totals
    })

@app.post("/time-logs")
def add_time_log(
    request: Request, 
    project_id: int = Form(...), 
    hours: float = Form(...), 
    date: str = Form(...), 
    description: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user or user.role == "client": # Clients can't add time
        return RedirectResponse(url="/time-logs", status_code=status.HTTP_403_FORBIDDEN)
    
    new_entry = models.TimeEntry(
        project_id=project_id,
        hours=hours,
        date=datetime.strptime(date, "%Y-%m-%d").date(),
        description=description
    )
    db.add(new_entry)
    db.commit()
    return RedirectResponse(url="/time-logs", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/invoices", response_class=HTMLResponse)
def invoices(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/login")
    
    query = db.query(models.Invoice).join(models.Project)
    if user.role == "client":
        query = query.filter(models.Project.client_id == user.client_id)
        
    invoices_list = query.order_by(models.Invoice.issued_date.desc()).all()
    return templates.TemplateResponse("invoices.html", {"request": request, "user": user, "invoices": invoices_list})

@app.get("/reports", response_class=HTMLResponse)
def reports(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user: return RedirectResponse(url="/login")
    
    # Summary Data for Charts
    # 1. Hours per project
    hours_data = {}
    time_query = db.query(models.TimeEntry).join(models.Project)
    if user.role == "client":
        time_query = time_query.filter(models.Project.client_id == user.client_id)
    
    for entry in time_query.all():
        pname = entry.project.name
        hours_data[pname] = hours_data.get(pname, 0) + entry.hours
        
    # 2. Monthly Earnings (or Spending for client)
    # Group invoices by month
    monthly_data = {}
    inv_query = db.query(models.Invoice).join(models.Project).filter(models.Invoice.status == "paid")
    if user.role == "client":
        inv_query = inv_query.filter(models.Project.client_id == user.client_id)
        
    for inv in inv_query.all():
        month_key = inv.issued_date.strftime("%Y-%m")
        monthly_data[month_key] = monthly_data.get(month_key, 0) + inv.amount
        
    # 3. Top Clients (Admin/Freelancer only)
    top_clients = {}
    if user.role in ["admin", "freelancer"]:
        clients = db.query(models.Client).all()
        for client in clients:
            # Sum paid invoices
            total = sum(i.amount for p in client.projects for i in p.invoices if i.status == "paid")
            if total > 0:
                top_clients[client.name] = total
    
    return templates.TemplateResponse("reports.html", {
        "request": request, 
        "user": user,
        "hours_data": hours_data,
        "monthly_data": monthly_data,
        "top_clients": sorted(top_clients.items(), key=lambda x: x[1], reverse=True)
    })

# --- Seeding ---
@app.on_event("startup")
def startup_event():
    db = next(get_db())
    if db.query(models.User).first():
        return # Already seeded
    
    # 1. Clients
    clients = [
        models.Client(name="TechCorp", email="contact@techcorp.com"),
        models.Client(name="DesignStudio", email="hello@designstudio.com"),
        models.Client(name="StartupInc", email="founder@startupinc.com")
    ]
    db.add_all(clients)
    db.commit() # Commit to get IDs
    
    # 2. Users
    # Admin, Freelancer, Client
    hashed_pw = get_password_hash("password") # Default password for all
    users = [
        models.User(username="admin", hashed_password=hashed_pw, role="admin"),
        models.User(username="freelancer", hashed_password=hashed_pw, role="freelancer"),
        models.User(username="client", hashed_password=hashed_pw, role="client", client_id=clients[0].id)
    ]
    db.add_all(users)
    db.commit()
    
    # 3. Projects
    projects = [
        models.Project(name="Website Redesign", status="active", deadline=date.today() + timedelta(days=30), budget=5000, client_id=clients[0].id),
        models.Project(name="Mobile App MVP", status="active", deadline=date.today() + timedelta(days=60), budget=12000, client_id=clients[2].id),
        models.Project(name="Logo Design", status="completed", deadline=date.today() - timedelta(days=10), budget=800, client_id=clients[1].id),
        models.Project(name="SEO Audit", status="on-hold", deadline=date.today() + timedelta(days=5), budget=1500, client_id=clients[0].id),
        models.Project(name="Maintenance", status="active", deadline=date.today() + timedelta(days=365), budget=2000, client_id=clients[1].id),
    ]
    db.add_all(projects)
    db.commit()
    
    # 4. Time Entries (20 random entries)
    import random
    entries = []
    descriptions = ["Frontend dev", "Meeting", "Backend logic", "Bug fixing", "Design review"]
    for _ in range(20):
        proj = random.choice(projects)
        entries.append(models.TimeEntry(
            project_id=proj.id,
            date=date.today() - timedelta(days=random.randint(0, 30)),
            hours=random.randint(1, 8),
            description=random.choice(descriptions)
        ))
    db.add_all(entries)
    
    # 5. Invoices
    invoices_data = [
        models.Invoice(project_id=projects[2].id, amount=800, issued_date=date.today()-timedelta(days=12), status="paid"),
        models.Invoice(project_id=projects[0].id, amount=2500, issued_date=date.today()-timedelta(days=5), status="sent"),
        models.Invoice(project_id=projects[1].id, amount=4000, issued_date=date.today(), status="draft"),
        models.Invoice(project_id=projects[3].id, amount=1500, issued_date=date.today()-timedelta(days=20), status="paid")
    ]
    db.add_all(invoices_data)
    db.commit()
    print("Database seeded!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
