from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Float, Date, DateTime
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String)  # "admin", "freelancer", "client"
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True) # Linked if role is client

    client = relationship("Client", back_populates="user")

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    email = Column(String)
    
    user = relationship("User", back_populates="client", uselist=False)
    projects = relationship("Project", back_populates="client")

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    status = Column(String)  # "active", "completed", "on-hold"
    deadline = Column(Date)
    budget = Column(Float)
    client_id = Column(Integer, ForeignKey("clients.id"))

    client = relationship("Client", back_populates="projects")
    time_entries = relationship("TimeEntry", back_populates="project")
    invoices = relationship("Invoice", back_populates="project")

class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    date = Column(Date, default=datetime.utcnow)
    hours = Column(Float)
    description = Column(String)

    project = relationship("Project", back_populates="time_entries")

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    amount = Column(Float)
    issued_date = Column(Date, default=datetime.utcnow)
    status = Column(String)  # "draft", "sent", "paid"

    project = relationship("Project", back_populates="invoices")
