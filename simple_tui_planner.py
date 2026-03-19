#!/usr/bin/env python3
"""
Simple TUI Trip Planner - Interactive terminal-based trip planning application
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleTripPlanner:
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
            print("Loading destinations data...")
            self.df = pd.read_csv("data/tourist_destinations_sorted.csv")
            print(f"✅ Loaded {len(self.df)} destinations successfully!")
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            sys.exit(1)
    
    def display_welcome(self):
        """Display welcome screen"""
        print("""
🌍 Welcome to Hannibal's Army Trip Planner!

Your intelligent travel companion for personalized trip recommendations.

This tool will help you:
• Find perfect destinations based on your preferences
• Match countries to your budget and travel style
• Generate detailed trip recommendations

Let's start planning your perfect trip! 🚀
        """)
    
    def get_user_input(self, prompt: str, options: List[str] = None, default: str = None) -> str:
        """Simple user input function"""
        if options:
            print(f"\n{prompt}")
            for i, option in enumerate(options, 1):
                print(f"{i}. {option}")
            
            while True:
                try:
                    choice = input(f"Select option (1-{len(options)})" + (f" [default: {default}]" if default else "") + ": ")
                    if not choice and default:
                        return default
                    choice_num = int(choice)
                    if 1 <= choice_num <= len(options):
                        return options[choice_num - 1]
                    else:
                        print("Invalid choice. Please try again.")
                except ValueError:
                    print("Please enter a valid number.")
        else:
            return input(f"{prompt}" + (f" [default: {default}]" if default else "") + ": ") or default
    
    def collect_user_preferences(self) -> Dict:
        """Collect initial user preferences"""
        print("\n📝 Let's gather your travel preferences...\n")
        
        preferences = {}
        
        # Destination type
        trip_types = ["Beach", "Adventure", "Historical", "Nature", "City", "Religious"]
        preferences['destination_type'] = self.get_user_input(
            "What type of trip do you want?",
            trip_types,
            "Beach"
        )
        
        # Budget
        budget_input = self.get_user_input(
            "What's your total budget (USD)? Leave empty for unlimited"
        )
        preferences['budget'] = float(budget_input) if budget_input else None
        
        # Duration
        preferences['duration'] = int(self.get_user_input(
            "Trip duration (days)",
            default="7"
        ))
        
        # Season
        seasons = ["Spring", "Summer", "Fall", "Winter"]
        preferences['season'] = self.get_user_input(
            "Preferred season?",
            seasons,
            "Summer"
        )
        
        # Travel style
        styles = ["Budget", "Mid-range", "Luxury"]
        preferences['travel_style'] = self.get_user_input(
            "Travel style?",
            styles,
            "Mid-range"
        )
        
        # Display summary
        self.display_preferences_summary(preferences)
        
        return preferences
    
    def display_preferences_summary(self, preferences: Dict):
        """Display summary of user preferences"""
        print(f"""
📋 Your Preferences:
• Trip Type: {preferences['destination_type']}
• Budget: {f"${preferences['budget']:,}" if preferences['budget'] else "Unlimited"}
• Duration: {preferences['duration']} days
• Season: {preferences['season']}
• Travel Style: {preferences['travel_style']}
        """)
        
        confirm = input("Are these preferences correct? (y/n): ").lower()
        if confirm != 'y':
            return self.collect_user_preferences()
        
        return preferences
    
    def match_countries_by_criteria(self, destination_type: str, budget: Optional[float] = None) -> pd.DataFrame:
        """Smart country matching based on type and budget"""
        print("\n🔍 Finding perfect countries for your trip...")
        
        # 1. Filter by destination type
        type_filtered = self.df[self.df['Type'].str.contains(destination_type, case=False, na=False)]
        
        if type_filtered.empty:
            print(f"❌ No destinations found for type: {destination_type}")
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
            print(f"Found {len(affordable_countries)} affordable countries")
        else:
            affordable_countries = country_stats
            print(f"Found {len(affordable_countries)} countries")
        
        # 4. Score and rank countries
        if affordable_countries.empty:
            print("❌ No countries match your budget criteria")
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
        print(f"Ranked top {len(result)} countries")
        
        return result
    
    def display_country_recommendations(self, countries: pd.DataFrame) -> str:
        """Display matched countries"""
        if countries.empty:
            return None
        
        print(f"""
🌍 Recommended Countries:
""")
        for i, (country, data) in enumerate(countries.iterrows(), 1):
            print(f"{i}. {country}")
            print(f"   • Avg Cost/Day: ${data['Avg Cost (USD/day)']:.0f}")
            print(f"   • Avg Rating: {data['Avg Rating']:.1f} ⭐")
            print(f"   • Destinations: {data['Destination Count']}")
            print(f"   • UNESCO Sites: {data['UNESCO Site']}")
            print(f"   • Score: {data['Score']:.2f}")
            print()
        
        while True:
            choice = input(f"Select a country (1-{len(countries)}) or 'back' to change preferences: ")
            if choice.lower() == 'back':
                return 'back'
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(countries):
                    return str(choice_num)
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number.")
    
    def generate_trip_recommendations(self, country: str, preferences: Dict) -> List[Dict]:
        """Generate detailed trip recommendations for selected country"""
        print(f"\n🎯 Creating personalized trip for {country}...")
        
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
            print("No seasonal matches, using type filter only")
        
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
        
        print(f"Found {len(top_destinations)} recommendations")
        
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
        print(f"\n🎉 Your Personalized {self.selected_country} Trip Plan")
        
        total_budget = preferences['budget']
        total_trip_cost = sum(r['total_cost'] for r in recommendations)
        
        # Summary
        print(f"""
📊 Trip Summary:
• Destination: {self.selected_country}
• Duration: {preferences['duration']} days
• Season: {preferences['season']}
• Trip Type: {preferences['destination_type']}
• Total Cost: ${total_trip_cost:,.0f}
        """)
        
        if total_budget:
            if total_trip_cost <= total_budget:
                print(f"• Under Budget: ${total_budget - total_trip_cost:,.0f}")
            else:
                print(f"• Over Budget: ${total_trip_cost - total_budget:,.0f}")
        
        # Detailed recommendations
        for i, rec in enumerate(recommendations, 1):
            print(f"""
📍 {i}. {rec['destination']}
   Type: {rec['type']}
   Rating: {rec['rating']:.1f} ⭐
   Daily Cost: ${rec['daily_cost']:.0f}
   Total Cost: ${rec['total_cost']:,.0f}
   Best Season: {rec['best_season']}
   UNESCO Site: {rec['unesco']}
   Annual Visitors: {rec['annual_visitors']}M
   
   Description: {rec['description']}
   
   Suggested Activities:
   """ + "\n   ".join(f"• {act}" for act in rec['activities']))
    
    def save_trip_plan(self, recommendations: List[Dict], preferences: Dict, country: str):
        """Save trip plan as JSON"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create trips directory if it doesn't exist
        trips_dir = "trip_plans"
        if not os.path.exists(trips_dir):
            os.makedirs(trips_dir)
        
        filename = f"{trips_dir}/trip_plan_{country}_{timestamp}.json"
        
        data = {
            'trip_plan': {
                'country': country,
                'preferences': preferences,
                'recommendations': recommendations,
                'generated_at': datetime.now().isoformat()
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"\n✅ Trip plan saved: {filename}")
    
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
                    if input("Would you like to try different preferences? (y/n): ").lower() != 'y':
                        break
                    continue
                
                # Stage 3: Display country options
                country_choice = self.display_country_recommendations(self.recommended_countries)
                
                if country_choice == 'back':
                    continue
                
                # Get selected country
                self.selected_country = self.recommended_countries.iloc[int(country_choice) - 1].name
                
                # Stage 4: Generate detailed recommendations
                self.trip_recommendations = self.generate_trip_recommendations(
                    self.selected_country, 
                    self.user_preferences
                )
                
                # Stage 5: Display detailed trip plan
                self.display_trip_plan(self.trip_recommendations, self.user_preferences)
                
                # Stage 6: Save options
                save_choice = input("\nWould you like to save this trip plan? (y/n): ").lower()
                if save_choice == 'y':
                    self.save_trip_plan(
                        self.trip_recommendations, 
                        self.user_preferences, 
                        self.selected_country
                    )
                
                if input("\nWould you like to plan another trip? (y/n): ").lower() != 'y':
                    print("\n👋 Thank you for using Hannibal's Army Trip Planner!")
                    break
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ An error occurred: {e}")
                logger.error(f"Error in main loop: {str(e)}")
                if input("Would you like to continue? (y/n): ").lower() != 'y':
                    break

def main():
    """Main entry point"""
    try:
        planner = SimpleTripPlanner()
        planner.run()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
