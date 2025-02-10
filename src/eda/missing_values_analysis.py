from abc import ABC, abstractmethod  # For implementing the template design pattern
import matplotlib.pyplot as plt  # For visualization
import pandas as pd  # For handling dataframes
import seaborn as sns  # For enhanced visualizations

# Abstract Base Class (ABC) to define a standard template for missing values analysis
class MissingValuesReportTemplate(ABC):
    """
    An abstract base class that enforces the implementation of missing values analysis.
    It provides a common interface for reporting and visualizing missing data in a DataFrame.
    """

    def missing_values_analysis(self, df: pd.DataFrame) -> None:
        """
        A template method that calls both reporting and visualization methods.
        This ensures a structured approach to missing values analysis.
        
        :param df: pd.DataFrame - The dataset to analyze for missing values.
        :return: None
        """
        self.missing_values_report(df)
        self.missing_values_visualization(df)

    @abstractmethod
    def missing_values_report(self, df: pd.DataFrame) -> None:
        """
        Abstract method that must be implemented to provide a report on missing values.
        
        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        pass

    @abstractmethod
    def missing_values_visualization(self, df: pd.DataFrame) -> None:
        """
        Abstract method that must be implemented to visualize missing values.
        
        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        pass


# Concrete implementation of the missing values analysis class
class MissingValuesReport(MissingValuesReportTemplate):
    """
    A concrete class that implements missing values reporting and visualization.
    """

    def missing_values_report(self, df: pd.DataFrame) -> None:
        """
        Prints a report of missing values per column.
        
        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        print("\nMissing Values Count by Column:")
        missing_values = df.isnull().sum()  # Count missing values per column
        missing_values = missing_values[missing_values > 0]  # Filter columns with missing values
        if missing_values.empty:
            print("No missing values found.")
        else:
            print(missing_values)

    def missing_values_visualization(self, df: pd.DataFrame) -> None:
        """
        Generates a heatmap to visualize missing values in the dataset.
        
        :param df: pd.DataFrame - The dataset to visualize.
        :return: None
        """
        if df.isnull().sum().sum() == 0:
            print("\nNo missing values to visualize.")
            return  # Exit function if there are no missing values

        print("\nVisualizing Missing Values...")
        plt.figure(figsize=(12, 8))
        sns.heatmap(df.isnull(), cbar=False, cmap="viridis", yticklabels=False)
        plt.title("Missing Values Heatmap")
        plt.show()
