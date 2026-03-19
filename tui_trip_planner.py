#!/usr/bin/env python3
"""
TUI Trip Planner - Interactive terminal-based trip planning application
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as RLTable, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import yaml

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Rich console
console = Console()

class TripPlannerTUI:
    def __init__(self):
        """Initialize TUI Trip Planner"""
        self.load_data()
        self.user_preferences = {}
        self.recommended_countries = None
        self.selected_country = None
        self.trip_recommendations = None
        
    def load_data(self):
        """Load destinations data"""
        try:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                task = progress.add_task("Loading destinations data...", total=None)
                self.df = pd.read_csv("data/tourist_destinations_sorted.csv")
                progress.update(task, description=f"Loaded {len(self.df)} destinations")
            console.print("✅ Data loaded successfully!", style="green")
        except Exception as e:
            console.print(f"❌ Error loading data: {e}", style="red")
            sys.exit(1)
    
    def display_welcome(self):
        """Display welcome screen"""
        welcome_text = """
🌍 Welcome to Hannibal's Army Trip Planner!

Your intelligent travel companion for personalized trip recommendations.

This tool will help you:
• Find perfect destinations based on your preferences
• Match countries to your budget and travel style
• Generate detailed trip recommendations
• Export your plans in multiple formats

Let's start planning your perfect trip! 🚀
        """
        console.print(Panel(welcome_text, title="🎯 Trip Planner", border_style="blue"))
    
    def collect_user_preferences(self) -> Dict:
        """Collect initial user preferences"""
        console.print("\n📝 Let's gather your travel preferences...\n", style="cyan")
        
        preferences = {}
        
        # Destination type
        preferences['destination_type'] = Prompt.ask(
            "What type of trip do you want?",
            choices=["Beach", "Adventure", "Historical", "Nature", "City", "Religious"],
            default="Beach",
            show_choices=True
        )
        
        # Budget
        budget_input = Prompt.ask(
            "What's your total budget (USD)? Leave empty for unlimited",
            default="",
            show_default=False
        )
        preferences['budget'] = float(budget_input) if budget_input else None
        
        # Duration
        preferences['duration'] = int(Prompt.ask(
            "Trip duration (days)?",
            default="7"
        ))
        
        # Season
        preferences['season'] = Prompt.ask(
            "Preferred season?",
            choices=["Spring", "Summer", "Fall", "Winter"],
            default="Summer",
            show_choices=True
        )
        
        # Travel style
        preferences['travel_style'] = Prompt.ask(
            "Travel style?",
            choices=["Budget", "Mid-range", "Luxury"],
            default="Mid-range",
            show_choices=True
        )
        
        # Display summary
        self.display_preferences_summary(preferences)
        
        return preferences
    
    def display_preferences_summary(self, preferences: Dict):
        """Display summary of user preferences"""
        table = Table(title="📋 Your Preferences", show_header=True, header_style="bold magenta")
        table.add_column("Preference", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Trip Type", preferences['destination_type'])
        table.add_row("Budget", f"${preferences['budget']:,}" if preferences['budget'] else "Unlimited")
        table.add_row("Duration", f"{preferences['duration']} days")
        table.add_row("Season", preferences['season'])
        table.add_row("Travel Style", preferences['travel_style'])
        
        console.print(table)
        
        if not Confirm.ask("\nAre these preferences correct?"):
            return self.collect_user_preferences()
        
        return preferences
    
    def match_countries_by_criteria(self, destination_type: str, budget: Optional[float] = None) -> pd.DataFrame:
        """Smart country matching based on type and budget"""
        console.print("\n🔍 Finding perfect countries for your trip...", style="cyan")
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Analyzing destinations...", total=None)
            
            # 1. Filter by destination type
            type_filtered = self.df[self.df['Type'].str.contains(destination_type, case=False, na=False)]
            
            if type_filtered.empty:
                console.print(f"❌ No destinations found for type: {destination_type}", style="red")
                return pd.DataFrame()
            
            # 2. Group by country and calculate statistics
            country_stats = type_filtered.groupby('Country').agg({
                'Avg Cost (USD/day)': 'mean',
                'Avg Rating': 'mean',
                'Destination Name': 'count',
                'UNESCO Site': lambda x: (x == 'Yes').sum()
            }).rename(columns={'Destination Name': 'Destination Count'})
            
            # 3. Filter by budget if provided
            if budget:
                daily_budget = budget / 7  # Weekly budget assumption
                affordable_countries = country_stats[
                    country_stats['Avg Cost (USD/day)'] <= daily_budget
                ]
                progress.update(task, description=f"Found {len(affordable_countries)} affordable countries")
            else:
                affordable_countries = country_stats
                progress.update(task, description=f"Found {len(affordable_countries)} countries")
            
            # 4. Score and rank countries
            if affordable_countries.empty:
                console.print("❌ No countries match your budget criteria", style="red")
                return pd.DataFrame()
            
            # Calculate composite score
            affordable_countries = affordable_countries.copy()
            affordable_countries['Score'] = (
                (affordable_countries['Avg Rating'] / 5.0) * 0.4 +  # Rating (normalized to 0-1)
                (affordable_countries['Destination Count'] / affordable_countries['Destination Count'].max()) * 0.3 +  # Variety
                (affordable_countries['UNESCO Site'] / affordable_countries['Destination Count']) * 0.2 +  # UNESCO sites
                (1 - affordable_countries['Avg Cost (USD/day)'] / affordable_countries['Avg Cost (USD/day)'].max()) * 0.1  # Cost efficiency
            )
            
            result = affordable_countries.sort_values('Score', ascending=False).head(10)
            progress.update(task, description=f"Ranked top {len(result)} countries")
        
        return result
    
    def display_country_recommendations(self, countries: pd.DataFrame) -> str:
        """Display matched countries with rich formatting"""
        if countries.empty:
            return None
        
        table = Table(title="🌍 Recommended Countries", show_header=True, header_style="bold magenta")
        table.add_column("No.", style="cyan", width=4)
        table.add_column("Country", style="magenta", min_width=15)
        table.add_column("Avg Cost/Day", style="green", justify="right")
        table.add_column("Avg Rating", style="yellow", justify="right")
        table.add_column("Destinations", style="blue", justify="right")
        table.add_column("UNESCO Sites", style="red", justify="right")
        table.add_column("Score", style="bold green", justify="right")
        
        for i, (country, data) in enumerate(countries.iterrows(), 1):
            table.add_row(
                str(i),
                country,
                f"${data['Avg Cost (USD/day)']:.0f}",
                f"{data['Avg Rating']:.1f} ⭐",
                str(data['Destination Count']),
                str(data['UNESCO Site']),
                f"{data['Score']:.2f}"
            )
        
        console.print(table)
        
        choice = Prompt.ask(
            "\nSelect a country (number) or type 'back' to change preferences",
            choices=[str(i) for i in range(1, len(countries) + 1)] + ["back", "quit"],
            default="1"
        )
        
        return choice
    
    def generate_trip_recommendations(self, country: str, preferences: Dict) -> List[Dict]:
        """Generate detailed trip recommendations for selected country"""
        console.print(f"\n🎯 Creating personalized trip for {country}...", style="cyan")
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Generating recommendations...", total=None)
            
            # 1. Get all destinations in selected country
            country_destinations = self.df[self.df['Country'] == country]
            
            # 2. Filter by season and type
            filtered = country_destinations[
                (country_destinations['Type'].str.contains(preferences['destination_type'], case=False, na=False)) &
                (country_destinations['Best Season'].str.contains(preferences['season'], case=False, na=False))
            ]
            
            if filtered.empty:
                # Fallback: just filter by type
                filtered = country_destinations[
                    country_destinations['Type'].str.contains(preferences['destination_type'], case=False, na=False)
                ]
                progress.update(task, description="No seasonal matches, using type filter only")
            
            # 3. Score destinations based on multiple factors
            filtered = filtered.copy()
            filtered['Trip_Score'] = (
                (filtered['Avg Rating'] / 5.0) * 0.4 +  # Rating
                (filtered['Annual Visitors (M)'] / filtered['Annual Visitors (M)'].max()) * 0.2 +  # Popularity
                (filtered['UNESCO Site'] == 'Yes') * 0.2 +  # UNESCO status
                (1 - filtered['Avg Cost (USD/day)'] / filtered['Avg Cost (USD/day)'].max()) * 0.2  # Cost efficiency
            )
            
            # 4. Get top destinations
            top_destinations = filtered.nlargest(min(5, len(filtered)), 'Trip_Score')
            
            progress.update(task, description=f"Found {len(top_destinations)} recommendations")
            
            recommendations = []
            for _, dest in top_destinations.iterrows():
                daily_cost = dest['Avg Cost (USD/day)']
                total_cost = daily_cost * preferences['duration']
                
                recommendation = {
                    'destination': dest['Destination Name'],
                    'type': dest['Type'],
                    'rating': dest['Avg Rating'],
                    'daily_cost': daily_cost,
                    'total_cost': total_cost,
                    'best_season': dest['Best Season'],
                    'unesco': dest['UNESCO Site'],
                    'annual_visitors': dest['Annual Visitors (M)'],
                    'description': f"Amazing {dest['Type'].lower()} destination in {country}",
                    'activities': self.generate_activities_suggestions(dest['Type'])
                }
                recommendations.append(recommendation)
            
            return recommendations
    
    def generate_activities_suggestions(self, destination_type: str) -> List[str]:
        """Generate activity suggestions based on destination type"""
        activities_map = {
            'Beach': ['Swimming', 'Sunbathing', 'Beach volleyball', 'Snorkeling', 'Surfing'],
            'Adventure': ['Hiking', 'Rock climbing', 'Zip-lining', 'Rafting', 'Mountain biking'],
            'Historical': ['Museum visits', 'Historical tours', 'Architecture photography', 'Cultural events'],
            'Nature': ['Wildlife watching', 'Bird watching', 'Nature photography', 'Hiking trails'],
            'City': ['City tours', 'Shopping', 'Fine dining', 'Nightlife', 'Museums'],
            'Religious': ['Temple visits', 'Meditation', 'Cultural ceremonies', 'Spiritual tours']
        }
        return activities_map.get(destination_type, ['Sightseeing', 'Local experiences', 'Cultural activities'])
    
    def display_trip_plan(self, recommendations: List[Dict], preferences: Dict):
        """Display detailed trip plan"""
        console.print(f"\n🎉 Your Personalized {self.selected_country} Trip Plan", style="bold green")
        
        total_budget = preferences['budget']
        total_trip_cost = sum(r['total_cost'] for r in recommendations)
        
        # Summary table
        summary_table = Table(title="📊 Trip Summary", show_header=True)
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")
        
        summary_table.add_row("Destination", self.selected_country)
        summary_table.add_row("Duration", f"{preferences['duration']} days")
        summary_table.add_row("Season", preferences['season'])
        summary_table.add_row("Trip Type", preferences['destination_type'])
        summary_table.add_row("Total Cost", f"${total_trip_cost:,.0f}")
        if total_budget:
            summary_table.add_row("Budget", f"${total_budget:,.0f}")
            if total_trip_cost <= total_budget:
                summary_table.add_row("Under Budget", f"${total_budget - total_trip_cost:,.0f}")
            else:
                summary_table.add_row("Over Budget", f"${total_trip_cost - total_budget:,.0f}")
        
        console.print(summary_table)
        
        # Detailed recommendations
        for i, rec in enumerate(recommendations, 1):
            rec_table = Table(title=f"📍 {i}. {rec['destination']}", show_header=False)
            rec_table.add_column("", style="white")
            
            details = f"""Type: {rec['type']}
Rating: {rec['rating']:.1f} ⭐
Daily Cost: ${rec['daily_cost']:.0f}
Total Cost: ${rec['total_cost']:,.0f}
Best Season: {rec['best_season']}
UNESCO Site: {rec['unesco']}
Annual Visitors: {rec['annual_visitors']}M

Description: {rec['description']}

Suggested Activities:
""" + "\n".join(f"• {act}" for act in rec['activities'])
            
            rec_table.add_row(details)
            console.print(rec_table)
    
    def run(self):
        """Main TUI application loop"""
        while True:
            try:
                # Welcome screen
                self.display_welcome()
                
                # Stage 1: Collect preferences
                self.user_preferences = self.collect_user_preferences()
                
                # Stage 2: Match countries
                self.recommended_countries = self.match_countries_by_criteria(
                    self.user_preferences['destination_type'], 
                    self.user_preferences['budget']
                )
                
                if self.recommended_countries.empty:
                    if not Confirm.ask("Would you like to try different preferences?"):
                        break
                    continue
                
                # Stage 3: Display country options
                country_choice = self.display_country_recommendations(self.recommended_countries)
                
                if country_choice == "back":
                    continue
                elif country_choice == "quit":
                    break
                
                # Get selected country
                self.selected_country = self.recommended_countries.iloc[int(country_choice) - 1].name
                
                # Stage 4: Generate detailed recommendations
                self.trip_recommendations = self.generate_trip_recommendations(
                    self.selected_country, 
                    self.user_preferences
                )
                
                # Stage 5: Display detailed trip plan
                self.display_trip_plan(self.trip_recommendations, self.user_preferences)
                
                if not Confirm.ask("\nWould you like to plan another trip?"):
                    console.print("\n👋 Thank you for using Hannibal's Army Trip Planner!", style="bold green")
                    break
                    
            except KeyboardInterrupt:
                console.print("\n👋 Goodbye!", style="bold green")
                break
            except Exception as e:
                console.print(f"\n❌ An error occurred: {e}", style="red")
                logger.error(f"Error in main loop: {str(e)}")
                if not Confirm.ask("Would you like to continue?"):
                    break

def main():
    """Main entry point"""
    try:
        planner = TripPlannerTUI()
        planner.run()
    except Exception as e:
        console.print(f"❌ Fatal error: {e}", style="red")
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
